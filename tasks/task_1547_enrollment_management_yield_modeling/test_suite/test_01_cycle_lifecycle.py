"""Cycle creation, phase-advance gates, and the close cascade."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    advance_cycle,
    advance_cycle_to_decisions_released,
    assert_admission_cycle,
    create_admitted_application,
    create_application_for_new_applicant,
    create_cycle,
    create_cycle_payload,
    create_waitlisted_application,
    get_waitlist_entry_for_application,
    get_success_data,
    is_valid_uuid,
    pay_deposit,
    refresh_application,
    schedule_intervention,
    set_clock,
    setup_open_cycle_with_program,
    submit_application,
    transition_application,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]


class TestCycleCreation:
    def test_create_cycle_success_initial_state(self, api):
        """PRD 3.1: "A new cycle is born in `SETUP` with all of its computed
        funnel counters at zero."
        PRD 3.1: "From these the cycle reports `admit_rate`: the count of
        applications that ever reached `ADMITTED` divided by
        `decisioned_count`, expressed to four decimal places round-half-up,
        and reported as 0 when `decisioned_count` is zero."

        Design: Corner/entities/create_cycle_success_initial_state
        """
        resp = api.create_cycle(create_cycle_payload(), MANAGER)
        cycle = validate_success(resp, 201)
        assert_admission_cycle(cycle)
        assert cycle["status"] == "SETUP", "A new cycle is born in SETUP"
        assert cycle["inquiry_count"] == 0
        assert cycle["application_count"] == 0
        assert cycle["admitted_count"] == 0
        assert cycle["deposited_count"] == 0
        assert cycle["enrolled_count"] == 0
        assert cycle["decisioned_count"] == 0
        assert cycle["admit_rate"] == 0, \
            "admit_rate is reported as 0 when decisioned_count is zero"
        assert is_valid_uuid(cycle["id"])


class TestCycleAdvanceGates:
    def test_open_without_programs_rejected(self, api):
        """PRD 3.1: "Moving `SETUP → OPEN` requires that the logical clock has
        reached `application_opens_at` (otherwise
        `ERR_PHASE_PRECONDITION_NOT_MET`) and that at least one program exists
        in the cycle (otherwise `ERR_CYCLE_HAS_NO_PROGRAMS`)."

        Design: Corner/validations/cycle_open_without_programs_rejected
        """
        set_clock(CLOCK_START)
        cycle = create_cycle()
        resp = api.advance_cycle(cycle["id"], "OPEN", MANAGER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_NO_PROGRAMS)
        after = validate_success(api.get_cycle(cycle["id"], MANAGER))
        assert after["status"] == "SETUP", \
            "A rejected advance leaves the cycle in SETUP"

    def test_review_close_before_application_deadline_rejected(self, api):
        """PRD 3.1: "Moving `OPEN → REVIEW_CLOSED` requires that the clock has
        reached `application_deadline_at`."
        PRD 2.9: "Sixth, clock-based window and deadline rules —
        `ERR_REVIEW_WINDOW_CLOSED`, `ERR_DEPOSIT_DEADLINE_PASSED`, and
        `ERR_PHASE_PRECONDITION_NOT_MET`."

        Design: Corner/validations/phase_precondition_too_early_rejected
        """
        setup = setup_open_cycle_with_program(name="EARLY")
        cycle_id = setup["cycle"]["id"]
        set_clock("2026-10-01T00:00:00Z")  # ahead of opens, before deadline
        resp = api.advance_cycle(cycle_id, "REVIEW_CLOSED", MANAGER)
        validate_error(resp, ApiErrorId.ERR_PHASE_PRECONDITION_NOT_MET)
        after = validate_success(api.get_cycle(cycle_id, MANAGER))
        assert after["status"] == "OPEN", \
            "A rejected advance leaves the cycle OPEN"


class TestDecisionReleaseGate:
    def test_release_blocked_while_application_in_review(self, api):
        """PRD 3.1: "Moving `REVIEW_CLOSED → DECISIONS_RELEASED` requires that
        no application of the cycle remains in `IN_REVIEW`,
        `COMMITTEE_REVIEW`, or `DECISION_PENDING`; any straggler fails the
        advance with `ERR_UNRESOLVED_APPLICATIONS`."

        Design: Difficulty/cross_entity_state_dependency/cycle_release_gated_by_unresolved_applications
        """
        setup = setup_open_cycle_with_program(name="ANT")
        cycle_id = setup["cycle"]["id"]
        pair = create_application_for_new_applicant(
            cycle_id, setup["program"]["id"], academic_score=73)
        transition_application(pair["application"]["id"], "IN_REVIEW")
        set_clock("2026-11-01T00:00:00Z")
        advance_cycle(cycle_id, "REVIEW_CLOSED")

        resp = api.advance_cycle(cycle_id, "DECISIONS_RELEASED", MANAGER)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_APPLICATIONS)
        after = validate_success(api.get_cycle(cycle_id, MANAGER))
        assert after["status"] == "REVIEW_CLOSED", \
            "The straggler blocks the release; the cycle stays REVIEW_CLOSED"

    def test_release_succeeds_after_blocker_withdraws(self, api):
        """PRD 3.1: "Moving `REVIEW_CLOSED → DECISIONS_RELEASED` requires that
        no application of the cycle remains in `IN_REVIEW`,
        `COMMITTEE_REVIEW`, or `DECISION_PENDING`; any straggler fails the
        advance with `ERR_UNRESOLVED_APPLICATIONS`."
        PRD 3.4: "Withdrawal is available throughout the pre-enrollment
        pipeline — from `SUBMITTED`, `IN_REVIEW`, `COMMITTEE_REVIEW`,
        `DECISION_PENDING`, and, as detailed in later sections, from
        `ADMITTED`, `DEPOSITED`, and `WAITLISTED`."

        Design: Difficulty/cross_entity_state_dependency/cycle_release_gated_by_unresolved_applications
        """
        setup = setup_open_cycle_with_program(name="ANT")
        cycle_id = setup["cycle"]["id"]
        pair = create_application_for_new_applicant(
            cycle_id, setup["program"]["id"], academic_score=73)
        transition_application(pair["application"]["id"], "IN_REVIEW")
        set_clock("2026-11-01T00:00:00Z")
        advance_cycle(cycle_id, "REVIEW_CLOSED")

        blocked = api.advance_cycle(cycle_id, "DECISIONS_RELEASED", MANAGER)
        validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_APPLICATIONS)

        transition_application(pair["application"]["id"], "WITHDRAWN")
        cycle = validate_success(
            api.advance_cycle(cycle_id, "DECISIONS_RELEASED", MANAGER))
        assert cycle["status"] == "DECISIONS_RELEASED", \
            "Withdrawing the straggler unblocks the advance"


class TestCycleCloseCascade:
    def test_close_cascades_and_terminal_lockdown(self, api):
        """PRD 3.1: "Every waitlist entry of the cycle's programs still in
        `ACTIVE` moves to `EXPIRED`; each expired entry's application, still
        sitting in `WAITLISTED`, is moved to `DENIED`; every melt intervention
        of the cycle's applications still in `SCHEDULED` moves to `CANCELLED`"
        PRD 3.1: "A request naming a `to_status` that the cycle's current
        status does not permit is rejected with `ERR_INVALID_STATE`"

        Design: Corner/state_machines/cycle_close_cascades_and_terminal_lockdown
        """
        setup = setup_open_cycle_with_program(name="CLS", capacity_seats=4,
                                              target_enrollment=2)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]

        waited = create_waitlisted_application(cycle_id, program_id,
                                               academic_score=70)
        deposited = create_admitted_application(cycle_id, program_id,
                                                academic_score=80)
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")
        pay_deposit(deposited["application"], deposited["applicant"])
        intervention = schedule_intervention(
            deposited["application"]["id"], advisor_id="advisor-Z",
            window_start_at="2027-05-10T09:00:00Z",
            window_end_at="2027-05-10T09:30:00Z")

        set_clock("2027-05-02T00:00:00Z")
        advance_cycle(cycle_id, "ENROLLMENT_TRACKING")
        set_clock("2027-06-01T00:00:00Z")
        cycle = validate_success(api.advance_cycle(cycle_id, "CLOSED",
                                                   MANAGER))
        assert cycle["status"] == "CLOSED"

        entry = get_waitlist_entry_for_application(
            waited["application"]["id"])
        assert entry["status"] == "EXPIRED", \
            "Close cascade expires ACTIVE waitlist entries"
        waited_app = refresh_application(waited["application"]["id"])
        assert waited_app["status"] == "DENIED", \
            "Each expired entry's WAITLISTED application is moved to DENIED"
        iv = get_success_data(api.get_intervention(intervention["id"],
                                                   MANAGER))
        assert iv["status"] == "CANCELLED", \
            "Close cascade cancels SCHEDULED interventions"

        advance_again = api.advance_cycle(cycle_id, "OPEN", MANAGER)
        validate_error(advance_again, ApiErrorId.ERR_INVALID_STATE)
        withdraw_denied = api.transition_application(
            waited["application"]["id"], "WITHDRAWN", OFFICER)
        validate_error(withdraw_denied, ApiErrorId.ERR_INVALID_STATE)
