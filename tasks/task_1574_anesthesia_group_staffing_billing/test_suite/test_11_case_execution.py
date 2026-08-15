"""Case execution gates and cascades: start/complete/cancel preconditions,
terminal lockdown, supersede side effects, conditional cascades, and
reschedule recompute (PRD §3.2, §3.3, §3.6)."""
from test_helpers import (
    SCHED,
    ApiErrorId,
    complete_case_at,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_roster,
    create_site,
    get_success_data,
    list_claims,
    list_stipend_entries,
    make_crna_headers,
    make_physician_headers,
    propose_and_confirm,
    propose_assignment,
    run_case_clock,
    set_clock,
    setup_case_with_confirmed_primary,
    setup_completed_solo_case,
    setup_site_fee_roster,
    setup_stipend_site,
    validate_error,
    api_client,
)


class TestCaseStartGates:
    def test_start_on_draft_roster_rejected(self, api):
        """PRD §3.6: "Starting is permitted only while the roster is
        `PUBLISHED` (else `ERR_ROSTER_NOT_PUBLISHED`), the case is `SCHEDULED`
        (else `ERR_CASE_NOT_SCHEDULED`), and the clock date equals the roster's
        `service_date` (else `ERR_CLOCK_DATE_MISMATCH`)."

        Design: Corner/state_machines/case_start_on_unpublished_roster_rejected
        """
        site = create_site()
        create_fee_schedule("P100", 5)
        roster = create_roster(site["id"])  # left DRAFT
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        set_clock("2026-08-10T09:00:00Z")
        resp = api.start_case(case["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_ROSTER_NOT_PUBLISHED)
        after = get_success_data(api.get_case(case["id"], SCHED))
        assert after["status"] == "SCHEDULED"
        assert after["actual_start_minute"] is None

    def test_start_on_wrong_clock_date_rejected(self, api):
        """PRD §3.6: "the clock date equals the roster's `service_date` (else
        `ERR_CLOCK_DATE_MISMATCH`)".

        Design: Corner/state_machines/case_start_on_wrong_clock_date_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        set_clock("2026-08-09T09:00:00Z")
        resp = api.start_case(case["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CLOCK_DATE_MISMATCH)
        after = get_success_data(api.get_case(case["id"], SCHED))
        assert after["status"] == "SCHEDULED"

    def test_start_twice_rejected(self, api):
        """PRD §3.6: "Starting is permitted only while ... the case is
        `SCHEDULED` (else `ERR_CASE_NOT_SCHEDULED`)".
        PRD §3.6: "a `Scheduler` starts the case, moving it `SCHEDULED →
        IN_PROGRESS` and stamping `actual_start_minute` from the clock
        minute-of-day."

        Design: Corner/state_machines/case_start_twice_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        started = run_case_clock(case["id"], "2026-08-10T09:00:00Z")
        assert started["actual_start_minute"] == 540
        resp = api.start_case(case["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_SCHEDULED)
        after = get_success_data(api.get_case(case["id"], SCHED))
        assert after["actual_start_minute"] == 540


class TestCaseCompleteGates:
    def test_complete_before_start_rejected(self, api):
        """PRD §3.6: "a case not `IN_PROGRESS` is rejected with
        `ERR_CASE_NOT_IN_PROGRESS`."

        Design: Corner/state_machines/case_complete_before_start_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        set_clock("2026-08-10T10:00:00Z")
        resp = api.complete_case(case["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_PROGRESS)
        after = get_success_data(api.get_case(case["id"], SCHED))
        assert after["status"] == "SCHEDULED"
        claims = get_success_data(
            api.list_claims(SCHED, params={"case_id": case["id"]}))
        rows = claims if isinstance(claims, list) else claims["data"]
        assert len(rows) == 0, "no claims materialize from a rejected complete"

    def test_complete_without_progressed_clock_rejected(self, api):
        """PRD §3.6: "It requires the clock date to equal the roster's
        `service_date` (else `ERR_CLOCK_DATE_MISMATCH`) and the clock
        minute-of-day to be strictly later than `actual_start_minute` (else
        `ERR_INVALID_ACTUAL_MINUTES`)".

        Design: Corner/state_machines/case_complete_without_progressed_clock_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        # Start at 09:00 (minute 540) and attempt completion at the same minute.
        run_case_clock(case["id"], "2026-08-10T09:00:00Z")
        resp = api.complete_case(case["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_ACTUAL_MINUTES)
        after = get_success_data(api.get_case(case["id"], SCHED))
        assert after["status"] == "IN_PROGRESS"
        assert after["actual_end_minute"] is None


class TestCaseCancelGates:
    def test_cancel_after_start_rejected(self, api):
        """PRD §3.6: "a case in any other state is rejected with
        `ERR_CASE_NOT_CANCELLABLE`."

        Design: Corner/state_machines/case_cancel_after_start_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        run_case_clock(case["id"], "2026-08-10T09:00:00Z")
        resp = api.cancel_case(case["id"], {"cancellation_reason": "CHANGED_MIND"},
                               SCHED)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_CANCELLABLE)
        after = get_success_data(api.get_case(case["id"], SCHED))
        assert after["status"] == "IN_PROGRESS"
        assert after["cancellation_notice_minutes"] is None


class TestCaseCompletedTerminalLockdown:
    def test_completed_case_rejects_cancel_and_start(self, api):
        """PRD §3.6: "a case in any other state is rejected with
        `ERR_CASE_NOT_CANCELLABLE`."
        PRD §3.6: "Starting is permitted only while ... the case is
        `SCHEDULED` (else `ERR_CASE_NOT_SCHEDULED`)".

        Design: Corner/state_machines/case_completed_terminal_lockdown
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        case_id = ctx["case"]["id"]
        resp_cancel = api.cancel_case(case_id, {"cancellation_reason": "TOO_LATE"},
                                      SCHED)
        validate_error(resp_cancel, ApiErrorId.ERR_CASE_NOT_CANCELLABLE)
        resp_start = api.start_case(case_id, SCHED)
        validate_error(resp_start, ApiErrorId.ERR_CASE_NOT_SCHEDULED)
        after = get_success_data(api.get_case(case_id, SCHED))
        assert after["status"] == "COMPLETED"
        # 60 actual minutes -> 9.0 units x 8000 = 72000.
        assert after["final_charge_cents"] == 72000
        assert after["actual_end_minute"] == 600


class TestAssignmentCancelAfterStart:
    def test_confirmed_assignment_not_cancellable_once_case_started(self, api):
        """PRD §3.3: "Cancellation is available while the assignment is
        `PROPOSED` or `CONFIRMED` and its case is still `SCHEDULED`; once the
        case is `IN_PROGRESS` or terminal, the attempt is rejected with
        `ERR_ASSIGNMENT_NOT_CANCELLABLE`."

        Design: Corner/state_machines/assignment_cancel_after_case_started_rejected
        """
        ctx = setup_case_with_confirmed_primary(
            provider_type="ANESTHESIOLOGIST", scheduled_start_minute=540,
            scheduled_end_minute=600)
        case_id = ctx["case"]["id"]
        run_case_clock(case_id, "2026-08-10T09:00:00Z")
        resp = api.cancel_assignment(ctx["primary"]["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE)
        after = get_success_data(api.get_assignment(ctx["primary"]["id"], SCHED))
        assert after["status"] == "CONFIRMED"
        case_after = get_success_data(api.get_case(case_id, SCHED))
        assert case_after["provisional_charge_cents"] == 72000, (
            "the rejected cancel must not null the provisional charge "
            f"(got {case_after['provisional_charge_cents']})")


class TestAssignmentAcceptGates:
    def test_second_accept_on_confirmed_rejected(self, api):
        """PRD §3.3: "the assignment must still be `PROPOSED` (else
        `ERR_ASSIGNMENT_NOT_PROPOSED`)".

        Design: Corner/state_machines/assignment_accept_twice_and_after_decline_rejected
        """
        site, fee, roster = setup_site_fee_roster(scheduled_day_end_minute=1200)
        p1 = create_crna("Crna One")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        assignment = propose_and_confirm(case["id"], p1["id"], "CRNA")
        resp = api.accept_assignment(assignment["id"], make_crna_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED)

    def test_accept_after_decline_rejected(self, api):
        """PRD §3.3: "Declining moves the assignment from `PROPOSED` to the
        terminal `DECLINED` state under the same ownership rule, with no
        further checks."
        PRD §3.3: "the assignment must still be `PROPOSED` (else
        `ERR_ASSIGNMENT_NOT_PROPOSED`)".

        Design: Corner/state_machines/assignment_accept_twice_and_after_decline_rejected
        """
        site, fee, roster = setup_site_fee_roster(scheduled_day_end_minute=1200)
        p2 = create_crna("Crna Two")
        case = create_case(roster["id"], scheduled_start_minute=660,
                           scheduled_end_minute=720)
        assignment = propose_assignment(case["id"], p2["id"], "CASE_PRIMARY")
        declined = get_success_data(api.decline_assignment(
            assignment["id"], make_crna_headers(p2["id"])))
        assert declined["status"] == "DECLINED"
        resp = api.accept_assignment(assignment["id"], make_crna_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED)


class TestAssignmentSupersede:
    def test_new_same_role_assignment_supersedes_proposed(self, api):
        """PRD §3.3: "Only one live assignment may exist per role per case.
        Creating a new assignment with the same `assignment_role` as an
        existing `PROPOSED` or `CONFIRMED` assignment on the same case
        automatically transitions the older one to `SUPERSEDED` (bumping its
        `version`); if the superseded assignment was a `CONFIRMED`
        `CASE_PRIMARY`, the case's `provisional_charge_cents` returns to null
        and stays there until the replacement confirms."

        Design: Corner/state_machines/assignment_supersede_replaces_same_role_proposed
        """
        site, fee, roster = setup_site_fee_roster(scheduled_day_end_minute=1200)
        p1 = create_crna("Crna One")
        p2 = create_crna("Crna Two")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=660)
        old = propose_assignment(case["id"], p1["id"], "CASE_PRIMARY")
        replacement = propose_assignment(case["id"], p2["id"], "CASE_PRIMARY")
        assert replacement["status"] == "PROPOSED"
        old_after = get_success_data(api.get_assignment(old["id"], SCHED))
        assert old_after["status"] == "SUPERSEDED"
        # Provisional stays null until the replacement confirms.
        mid = get_success_data(api.get_case(case["id"], SCHED))
        assert mid["provisional_charge_cents"] is None
        get_success_data(api.accept_assignment(replacement["id"],
                                               make_crna_headers(p2["id"])))
        after = get_success_data(api.get_case(case["id"], SCHED))
        # 120 scheduled min -> 13.0 units; CRNA solo context CF 7500 -> 97500.
        assert after["provisional_charge_cents"] == 97500


class TestConditionalCascades:
    def test_proposed_directing_closes_completed_without_claim(self, api):
        """PRD §3.6: "Every `PROPOSED` or `CONFIRMED` assignment on the case
        closes out to `COMPLETED`, each bumping its own `version`."
        PRD §3.6: "One `DRAFT` billing claim is auto-created per assignment
        that was `CONFIRMED` at the moment of completion — assignments still
        `PROPOSED` at completion generate no claim at all."

        Design: Corner/state_machines/case_completion_closes_proposed_directing_without_claim
        """
        site = create_site()
        create_fee_schedule("P100", 5)
        director = create_physician("Dr. Direct")
        crna = create_crna("Crna One")
        roster = create_published_roster(site["id"], required_primary_slots=1,
                                         scheduled_day_end_minute=1200)
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        propose_and_confirm(case["id"], crna["id"], "CRNA", "CASE_PRIMARY")
        # Directing assignment left PROPOSED (never accepted).
        directing = propose_assignment(case["id"], director["id"],
                                       "CASE_DIRECTING")
        run_case_clock(case["id"], "2026-08-10T09:00:00Z",
                       "2026-08-10T10:00:00Z")
        completed = get_success_data(api.complete_case(case["id"], SCHED))
        dir_after = get_success_data(api.get_assignment(directing["id"], SCHED))
        assert dir_after["status"] == "COMPLETED", \
            "PROPOSED directing closes out COMPLETED via the cascade"
        claims = list_claims({"case_id": case["id"]})
        assert len(claims) == 1, "PROPOSED-at-completion directing generates no claim"
        assert claims[0]["modifier_code"] == "QZ"
        # 60 actual min -> 9.0 units x CRNA solo 7500 = 67500.
        assert claims[0]["charge_cents"] == 67500
        assert completed["final_charge_cents"] == 67500
        audits = get_success_data(
            api.list_audits(SCHED, params={"roster_id": roster["id"]}))
        audit_rows = audits if isinstance(audits, list) else audits["data"]
        assert len(audit_rows) == 0, (
            "no CONFIRMED directing at completion -> no TEFRA_GAP finding and "
            "no audit")

    def test_cancel_with_unconfirmed_primary_creates_no_standby(self, api):
        """PRD §3.6: "Standby pay then applies when the `CASE_PRIMARY`
        assignment was `CONFIRMED` at cancel time and a stipend agreement
        covers the site and date".
        PRD §3.6: "All `PROPOSED` and `CONFIRMED` assignments on the case
        transition to `CANCELLED`, each bumping its own `version`".

        Design: Corner/state_machines/case_cancel_with_unconfirmed_primary_creates_no_standby
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"standby_full_cents": 30000},
            roster_kwargs={"required_primary_slots": 1,
                           "scheduled_day_end_minute": 1200})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        case = create_case(roster["id"], scheduled_start_minute=600,
                           scheduled_end_minute=660)
        assignment = propose_assignment(case["id"], provider["id"],
                                        "CASE_PRIMARY")  # never accepted
        set_clock("2026-08-10T09:30:00Z")
        cancelled = get_success_data(api.cancel_case(
            case["id"], {"cancellation_reason": "SURGEON_UNAVAILABLE"}, SCHED))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_notice_minutes"] == 30
        asg_after = get_success_data(api.get_assignment(assignment["id"], SCHED))
        assert asg_after["status"] == "CANCELLED"
        entries = list_stipend_entries({"provider_id": provider["id"]})
        assert len(entries) == 0, (
            "primary only PROPOSED at cancel -> no STANDBY despite short "
            "notice and a covering agreement")


class TestRosterPostureBubbleUp:
    def test_posture_flips_to_staffed_at_exactly_required_slots(self, api):
        """PRD §3.1: "A roster reads `STAFFED` exactly when the count of
        `CONFIRMED` `CASE_PRIMARY` assignments across the roster's cases
        reaches `required_primary_slots`, and `UNDERSTAFFED` otherwise".

        Design: Corner/state_machines/roster_posture_flips_staffed_when_slots_filled
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=2,
                                                  scheduled_day_end_minute=1200)
        p1 = create_crna("Crna One")
        p2 = create_crna("Crna Two")
        case_a = create_case(roster["id"], scheduled_start_minute=540,
                             scheduled_end_minute=600)
        case_b = create_case(roster["id"], scheduled_start_minute=660,
                             scheduled_end_minute=720)
        a1 = propose_assignment(case_a["id"], p1["id"], "CASE_PRIMARY")
        a2 = propose_assignment(case_b["id"], p2["id"], "CASE_PRIMARY")
        before = get_success_data(api.get_roster(roster["id"], SCHED))
        assert before["posture"] == "UNDERSTAFFED"
        get_success_data(api.accept_assignment(a1["id"], make_crna_headers(p1["id"])))
        one = get_success_data(api.get_roster(roster["id"], SCHED))
        assert one["posture"] == "UNDERSTAFFED", "one short of two required slots"
        get_success_data(api.accept_assignment(a2["id"], make_crna_headers(p2["id"])))
        two = get_success_data(api.get_roster(roster["id"], SCHED))
        assert two["posture"] == "STAFFED", "reaching the slot count flips posture"


class TestProvisionalRecomputedOnReschedule:
    def test_reschedule_recomputes_provisional_charge(self, api):
        """PRD §3.2: "an accepted reschedule re-runs the full safety battery
        of §3.3 for the case's `PROPOSED` and `CONFIRMED` assignments —
        supervision ratio for directing assignments, double-booking and
        rest-buffer checks for the primary — and, when a primary is currently
        `CONFIRMED`, recomputes `provisional_charge_cents` against the new
        scheduled minutes using the same forward-looking math as assignment
        acceptance."

        Design: Corner/calculations/provisional_charge_recomputed_on_reschedule
        """
        ctx = setup_case_with_confirmed_primary(
            provider_type="ANESTHESIOLOGIST", base_units=5,
            scheduled_start_minute=540, scheduled_end_minute=660,
            scheduled_day_end_minute=1200)
        case_id = ctx["case"]["id"]
        before = get_success_data(api.get_case(case_id, SCHED))
        assert before["provisional_charge_cents"] == 104000
        patched = get_success_data(api.reschedule_case(
            case_id, {"scheduled_start_minute": 540, "scheduled_end_minute": 720,
                      "expected_case_version": before["version"]}, SCHED))
        # 180 scheduled min -> 12.0 time units -> 17.0 units x 8000 = 136000.
        assert patched["provisional_charge_cents"] == 136000, (
            f"provisional must recompute in the same PATCH response, got "
            f"{patched['provisional_charge_cents']}")
