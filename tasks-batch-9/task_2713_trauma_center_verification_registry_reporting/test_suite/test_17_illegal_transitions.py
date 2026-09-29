"""Illegal transitions across every lifecycle, and the two writes that are legal.

Each lifecycle in the program refuses the transitions its ladder does not draw, and each
refusal names the state error belonging to that entity rather than a generic conflict.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    ABSTRACTOR_1_USER_ID,
    AbstractionStatus,
    ActionType,
    ActivityKind,
    AgreementStatus,
    CompletionStatus,
    CycleStatus,
    CycleType,
    DIRECTOR_2_USER_ID,
    DeficiencyClass,
    DeficiencyStatus,
    DesignationLevel,
    PM_1,
    PiEventType,
    PiSeverity,
    PiStatus,
    ReadinessPosture,
    TierCode,
    TriageReviewStatus,
    VALIDATOR_1_USER_ID,
    VALIDATOR_2_USER_ID,
    ValidationStatus,
    VerifiedStatus,
    assert_cohort_partition,
    assert_criteria_deficiency,
    assert_decimal,
    assert_instant,
    assert_pi_partition,
    assert_surveyor_booking,
    assert_verification_cycle,
    factories as f,
    fixtures as fx,
    make_registry_validator_headers,
    make_system_admin_headers,
    make_trauma_medical_director_headers,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)

SURVEYOR_3 = "u_surveyor_3"


def _cycle_under_review(
    api: ApiClient,
    name: str,
    state_code: str,
    site_visit_date: str,
    designation_level: str = DesignationLevel.LEVEL_II,
):
    """A national cycle walked to UNDER_REVIEW so its findings can be recorded."""
    center = fx.create_center(
        api, name=name, state_code=state_code, designation_level=designation_level
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date=site_visit_date,
    )
    fx.submit_cycle(api, cycle)
    fx.book_surveyor(
        api,
        cycle,
        surveyor_user_id=SURVEYOR_3,
        window_start=site_visit_date.replace("T13:00:00Z", "T08:00:00Z"),
        window_end=site_visit_date.replace("T13:00:00Z", "T17:00:00Z"),
    )
    fx.schedule_site_visit(api, cycle, site_visit_date)
    fx.begin_review(api, cycle)
    return center, fx.get_cycle(api, cycle["id"])


class TestVerificationCycleMinting:
    """Opening a cycle mints its whole system surface before anyone touches it."""

    def test_a_new_cycle_is_minted_in_prep_with_no_decision_and_no_findings(
        self, api: ApiClient
    ) -> None:
        """Version one, status PREP, an undecided outcome and three empty finding counters.

        Design: Corner/entities/verification_cycle_system_fields_are_server_minted_on_create
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Silver Lake Trauma",
            state_code="NV",
            designation_level=DesignationLevel.LEVEL_II,
        )

        created = api.create_verification_cycle(
            f.verification_cycle_payload(
                center_id=center["id"],
                cycle_type=CycleType.NATIONAL_VERIFICATION,
                site_visit_date="2026-12-02T13:00:00Z",
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        cycle = validate_success(created, 201)
        assert_verification_cycle(cycle, center["id"])
        assert cycle["version"] == 1
        assert cycle["status"] == CycleStatus.PREP
        assert cycle["decided_at"] is None
        assert cycle["decision_effective_date"] is None
        assert cycle["open_type_i_count"] == 0
        assert cycle["open_type_ii_count"] == 0
        assert cycle["open_type_iii_count"] == 0
        assert_decimal(cycle["readiness_score"], 82.00, "readiness_score")


class TestVerificationCycleIllegalTransitions:
    """The cycle ladder runs through submission and the site visit before deliberation."""

    def test_beginning_review_straight_from_prep_is_an_invalid_cycle_state(
        self, api: ApiClient
    ) -> None:
        """Deliberation cannot skip submission and the scheduled visit.

        Design: Corner/state_machines/begin_review_from_prep_returns_invalid_cycle_state
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Cypress Trauma",
            state_code="LA",
            designation_level=DesignationLevel.LEVEL_II,
        )
        cycle = fx.create_cycle(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-10-08T13:00:00Z",
        )
        assert cycle["status"] == CycleStatus.PREP

        refused = api.begin_cycle_review(
            cycle["id"], make_verification_reviewer_headers()
        )
        validate_error(refused, E.INVALID_CYCLE_STATE, 409)

        untouched = fx.get_cycle(api, cycle["id"])
        assert untouched["status"] == CycleStatus.PREP
        assert untouched["version"] == 1, "a refused transition is not a write"

    def test_scheduling_the_site_visit_moves_a_submitted_cycle_and_bumps_its_version(
        self, api: ApiClient
    ) -> None:
        """The confirmed date overwrites the planned one and the booking is untouched.

        Design: Corner/state_machines/schedule_site_visit_moves_submitted_cycle_and_bumps_version
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Cardinal Trauma",
            state_code="IN",
            designation_level=DesignationLevel.LEVEL_II,
        )
        cycle = fx.cycle_submitted(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-10-05T13:00:00Z",
        )
        assert cycle["status"] == CycleStatus.SUBMITTED
        booking = fx.book_surveyor(
            api,
            cycle,
            surveyor_user_id=SURVEYOR_3,
            window_start="2026-10-12T08:00:00Z",
            window_end="2026-10-12T17:00:00Z",
        )
        version_before = fx.get_cycle(api, cycle["id"])["version"]

        accepted = api.schedule_site_visit(
            cycle["id"],
            f.schedule_site_visit_payload("2026-10-12T13:00:00Z"),
            make_verification_reviewer_headers(),
        )
        scheduled = validate_success(accepted, 200)
        assert scheduled["status"] == CycleStatus.SITE_VISIT_SCHEDULED
        assert_instant(
            scheduled["site_visit_date"], "2026-10-12T13:00:00Z", "site_visit_date"
        )
        assert scheduled["version"] == version_before + 1

        bookings = get_success_data(
            api.list_surveyor_bookings(cycle["id"], make_verification_reviewer_headers())
        )
        assert [row["id"] for row in bookings] == [booking["id"]]
        assert_surveyor_booking(bookings[0], cycle["id"])
        assert_instant(
            bookings[0]["window_start"], "2026-10-12T08:00:00Z", "window_start"
        )
        assert_instant(bookings[0]["window_end"], "2026-10-12T17:00:00Z", "window_end")


class TestPiLoopIllegalTransitions:
    """A loop is closed from the planning state, never straight from identification."""

    def test_closing_a_loop_still_identified_is_an_invalid_pi_state(
        self, api: ApiClient
    ) -> None:
        """The refusal names the state, not the open-actions safety rule behind it.

        Design: Corner/state_machines/close_loop_from_identified_returns_invalid_pi_state
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Birchwood Trauma",
            state_code="MT",
            designation_level=DesignationLevel.LEVEL_III,
        )
        event = fx.create_pi_event(
            api,
            center["id"],
            event_type=PiEventType.MORTALITY_REVIEW,
            severity=PiSeverity.HIGH,
        )
        assert event["status"] == PiStatus.IDENTIFIED

        refused = api.close_pi_loop(
            event["id"],
            f.close_loop_payload("Reviewed informally at the morning huddle."),
            make_trauma_medical_director_headers(DIRECTOR_2_USER_ID),
        )
        validate_error(refused, E.INVALID_PI_STATE, 409)
        assert refused.json()["data"]["error_id"] != E.OPEN_ACTIONS_BLOCK_LOOP_CLOSURE, (
            "an event with no actions at all fails on its state, not on its action set"
        )

        untouched = fx.get_event(api, event["id"])
        assert untouched["status"] == PiStatus.IDENTIFIED
        assert untouched["closed_at"] is None
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )

    def test_verifying_an_action_that_is_still_open_is_an_invalid_action_state(
        self, api: ApiClient
    ) -> None:
        """Verification follows completion, so an open action cannot be verified.

        Design: Corner/state_machines/verify_corrective_action_while_open_returns_invalid_action_state
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Copper Basin Trauma",
            state_code="AZ",
            designation_level=DesignationLevel.LEVEL_II,
        )
        event, action = fx.pi_loop_at_action_planned(
            api,
            center["id"],
            event_type=PiEventType.TRANSFER_DELAY,
            severity=PiSeverity.MEDIUM,
            action_type=ActionType.PROTOCOL_CHANGE,
            owner_user_id=PM_1,
            due_at="2026-09-15T00:00:00Z",
        )
        assert event["status"] == PiStatus.ACTION_PLANNED
        assert action["completion_status"] == CompletionStatus.OPEN

        refused = api.verify_corrective_action(
            action["id"], make_verification_reviewer_headers()
        )
        validate_error(refused, E.INVALID_ACTION_STATE, 409)

        untouched = fx.get_corrective_action(api, event["id"], action["id"])
        assert untouched["completion_status"] == CompletionStatus.OPEN
        assert untouched["completed_at"] is None
        assert untouched["verified_at"] is None
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )


class TestDeficiencyIllegalTransitions:
    """A finding is closed out of remediation, and closure is terminal."""

    def test_closing_a_deficiency_that_was_never_remediated_is_refused(
        self, api: ApiClient
    ) -> None:
        """Acceptance needs a remediation packet to accept.

        Design: Corner/state_machines/close_deficiency_while_open_returns_invalid_deficiency_state
        """
        fx.anchor_clock(api)
        center, cycle = _cycle_under_review(
            api, "Wheatfield Trauma", "OK", "2026-10-22T13:00:00Z"
        )
        deficiency = fx.record_deficiency(
            api,
            cycle,
            criterion_code="CD-05-02",
            deficiency_class=DeficiencyClass.TYPE_II_MAJOR,
            remediation_due_at="2026-09-20T00:00:00Z",
        )
        assert_criteria_deficiency(deficiency, cycle["id"])
        assert deficiency["status"] == DeficiencyStatus.OPEN

        refused = api.close_criteria_deficiency(
            deficiency["id"], make_verification_reviewer_headers()
        )
        validate_error(refused, E.INVALID_DEFICIENCY_STATE, 409)

        untouched = fx.get_deficiency(api, cycle["id"], deficiency["id"])
        assert untouched["status"] == DeficiencyStatus.OPEN
        assert untouched["closed_at"] is None

        after_cycle = fx.get_cycle(api, cycle["id"])
        assert after_cycle["open_type_ii_count"] == 1
        assert_decimal(after_cycle["readiness_score"], 76.00, "readiness_score")

    def test_a_closed_deficiency_refuses_a_second_remediation_packet(
        self, api: ApiClient
    ) -> None:
        """A fresh concurrency token does not reopen a terminal finding.

        Design: Corner/state_machines/remediation_on_closed_deficiency_is_rejected_by_terminal_lockdown
        """
        fx.anchor_clock(api)
        center, cycle = _cycle_under_review(
            api,
            "Kestrel Trauma",
            "WY",
            "2026-10-30T13:00:00Z",
            designation_level=DesignationLevel.LEVEL_III,
        )
        deficiency = fx.record_deficiency(
            api,
            cycle,
            criterion_code="CD-02-07",
            deficiency_class=DeficiencyClass.TYPE_III_MINOR,
            remediation_due_at="2026-09-10T00:00:00Z",
        )
        fx.submit_remediation(
            api,
            cycle,
            deficiency,
            remediation_note="Signage and public education board updated.",
        )
        closed = fx.close_deficiency(api, cycle, deficiency)
        assert closed["status"] == DeficiencyStatus.CLOSED

        current_version = fx.get_cycle(api, cycle["id"])["version"]
        refused = api.submit_remediation(
            deficiency["id"],
            f.remediation_payload(
                current_version, "Second packet submitted after the finding was closed."
            ),
            make_trauma_program_manager_headers(center["id"]),
        )
        validate_error(refused, E.INVALID_DEFICIENCY_STATE, 409)
        assert refused.json()["data"]["error_id"] != E.STALE_CYCLE_VERSION, (
            "the token supplied was the current one, so the state is what refuses"
        )

        untouched = fx.get_deficiency(api, cycle["id"], deficiency["id"])
        assert untouched["status"] == DeficiencyStatus.CLOSED
        assert untouched["remediation_note"] == "Signage and public education board updated."

        after_cycle = fx.get_cycle(api, cycle["id"])
        assert after_cycle["open_type_iii_count"] == 0
        assert_decimal(after_cycle["readiness_score"], 82.00, "readiness_score")


class TestReferralAgreementIllegalTransitions:
    """Termination applies to an agreement in force, not to a draft."""

    def test_terminating_a_draft_agreement_is_an_invalid_agreement_state(
        self, api: ApiClient
    ) -> None:
        """A draft is abandoned rather than terminated, so the write is refused.

        Design: Corner/state_machines/terminate_draft_agreement_returns_invalid_agreement_state
        """
        fx.anchor_clock(api)
        referring = fx.create_center(
            api,
            name="Salt Marsh Trauma",
            state_code="SC",
            designation_level=DesignationLevel.LEVEL_III,
        )
        receiving = fx.create_center(
            api,
            name="Palmetto Regional Trauma",
            state_code="SC",
            designation_level=DesignationLevel.LEVEL_I,
        )
        agreement = fx.create_agreement(
            api,
            referring["id"],
            receiving["id"],
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
            guaranteed_acceptance_minutes=30,
        )
        assert agreement["agreement_status"] == AgreementStatus.DRAFT

        refused = api.terminate_referral_agreement(
            agreement["id"],
            f.terminate_agreement_payload("Draft withdrawn before either party signed."),
            make_trauma_program_manager_headers(referring["id"]),
        )
        validate_error(refused, E.INVALID_AGREEMENT_STATE, 409)

        untouched = fx.get_agreement(api, referring["id"], agreement["id"])
        assert untouched["agreement_status"] == AgreementStatus.DRAFT
        assert untouched["terminated_at"] is None


class TestOutreachIllegalTransitions:
    """Rejection is terminal for an activity, and the ledger reflects that."""

    def test_rejecting_an_already_rejected_activity_is_an_invalid_outreach_state(
        self, api: ApiClient
    ) -> None:
        """The weighted credit stays recorded on the activity but never returns to the ledger.

        Design: Corner/state_machines/reject_already_rejected_outreach_returns_invalid_outreach_state
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Grand Mesa Trauma",
            state_code="CO",
            designation_level=DesignationLevel.LEVEL_II,
        )
        activity = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.PROFESSIONAL_EDUCATION,
            event_date="2026-05-05T00:00:00Z",
            credit_hours=2.00,
            audience_count=40,
        )
        fx.verify_outreach(api, activity)
        rejected = fx.reject_outreach(
            api, activity, rejection_reason="Curriculum hours could not be substantiated."
        )
        assert rejected["verified_status"] == VerifiedStatus.REJECTED

        refused = api.reject_outreach_activity(
            activity["id"],
            f.reject_outreach_payload("Second rejection attempted on the same activity."),
            make_trauma_medical_director_headers(),
        )
        validate_error(refused, E.INVALID_OUTREACH_STATE, 409)

        untouched = fx.get_outreach_activity(api, center["id"], activity["id"])
        assert untouched["verified_status"] == VerifiedStatus.REJECTED
        assert_decimal(untouched["weighted_credit_hours"], 2.00, "weighted_credit_hours")

        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            0.00,
            "outreach_credit_hours_ytd",
        )


class TestAbstractionAndCaseIllegalTransitions:
    """Adjudication happens once, triage is reviewed once, and a lock is not repeatable."""

    def test_a_second_validation_of_the_same_abstraction_is_already_adjudicated(
        self, api: ApiClient
    ) -> None:
        """The second validator's attempt does not overwrite the first validator's name.

        Design: Corner/state_machines/validate_already_validated_abstraction_returns_already_adjudicated
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Two Rivers Trauma",
            state_code="TN",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-TR1",
            arrival_at="2026-07-18T12:00:00Z",
            injury_severity_score=20,
            los_hours=44.00,
        )
        abstraction = fx.submit_abstraction(
            api,
            case,
            iss_abstracted=20,
            gcs_arrival=12,
            mechanism_code="MVC",
            ed_departure_at="2026-07-18T15:00:00Z",
        )
        fx.validate_abstraction(api, abstraction, validator_user_id=VALIDATOR_1_USER_ID)

        refused = api.validate_abstraction(
            abstraction["id"], make_registry_validator_headers(VALIDATOR_2_USER_ID)
        )
        validate_error(refused, E.ABSTRACTION_ALREADY_ADJUDICATED, 409)

        untouched = fx.get_abstraction(api, case["id"], abstraction["id"])
        assert untouched["validation_status"] == ValidationStatus.VALIDATED
        assert untouched["validated_by_user_id"] == VALIDATOR_1_USER_ID

        after_case = fx.get_case(api, case["id"])
        assert after_case["abstraction_status"] == AbstractionStatus.VALIDATED
        assert after_case["effective_iss"] == 20

    def test_a_second_triage_review_of_the_same_case_is_already_reviewed(
        self, api: ApiClient
    ) -> None:
        """The first verdict stands and no under-triage cascade is set in motion.

        Design: Corner/state_machines/second_triage_review_returns_triage_already_reviewed
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Sunflower Trauma",
            state_code="KS",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-SF1",
            arrival_at="2026-07-21T06:00:00Z",
            injury_severity_score=27,
            los_hours=66.00,
        )
        reviewed = fx.triage_review(
            api, case, triage_review_status=TriageReviewStatus.APPROPRIATE
        )
        assert reviewed["triage_review_status"] == TriageReviewStatus.APPROPRIATE

        refused = api.triage_review_case(
            case["id"],
            f.triage_review_payload(TriageReviewStatus.UNDER_TRIAGE_CONFIRMED),
            make_trauma_medical_director_headers(),
        )
        validate_error(refused, E.TRIAGE_ALREADY_REVIEWED, 409)

        untouched = fx.get_case(api, case["id"])
        assert untouched["triage_review_status"] == TriageReviewStatus.APPROPRIATE

        assert (
            get_success_data(
                api.list_pi_events(
                    make_system_admin_headers(), {"center_id": center["id"]}
                )
            )
            == []
        )
        after_center = fx.get_center(api, center["id"])
        assert_decimal(
            after_center["under_triage_rate_pct"], 0.00, "under_triage_rate_pct"
        )
        assert_pi_partition(after_center, open_count=0, closed_count=0)
        assert after_center["readiness_posture"] == ReadinessPosture.READY
        assert_cohort_partition(after_center, included=1, excluded=0)

    def test_a_second_lock_on_a_locked_case_is_already_locked(
        self, api: ApiClient
    ) -> None:
        """The repeated lock is refused on the lock itself, not on the abstraction beneath it.

        Design: Corner/state_machines/second_lock_on_locked_case_returns_case_already_locked
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Fort Hill Trauma",
            state_code="VA",
            designation_level=DesignationLevel.LEVEL_I,
            tier_code=TierCode.TIER_1_FULL,
        )
        case, _ = fx.case_locked(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-FH1",
            arrival_at="2026-07-16T02:00:00Z",
            injury_severity_score=31,
            los_hours=80.00,
            abstractor_user_id=ABSTRACTOR_1_USER_ID,
            iss_abstracted=31,
            gcs_arrival=7,
            mechanism_code="GSW",
            ed_departure_at="2026-07-16T04:30:00Z",
        )
        assert case["abstraction_status"] == AbstractionStatus.LOCKED

        refused = api.lock_registry_case(
            case["id"], make_trauma_program_manager_headers(center["id"])
        )
        validate_error(refused, E.CASE_ALREADY_LOCKED, 409)
        assert refused.json()["data"]["error_id"] != E.ABSTRACTION_NOT_VALIDATED, (
            "the abstraction beneath the lock was validated before the first lock"
        )

        untouched = fx.get_case(api, case["id"])
        assert untouched["abstraction_status"] == AbstractionStatus.LOCKED
        assert_instant(untouched["locked_at"], "2026-08-01T00:00:00Z", "locked_at")
