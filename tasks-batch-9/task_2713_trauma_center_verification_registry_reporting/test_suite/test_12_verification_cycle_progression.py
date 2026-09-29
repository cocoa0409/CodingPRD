"""How a verification cycle moves, and what recomputed readiness does to it.

Some of the cycle's transitions are nobody's request: they follow from a score that was
recomputed because a deficiency, an event or the clock changed underneath it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    CycleStatus,
    CycleType,
    Decision,
    DeficiencyClass,
    DeficiencyStatus,
    DesignationLevel,
    NationalVerificationStatus,
    PiEventType,
    PiSeverity,
    ReadinessPosture,
    SURVEYOR_1,
    assert_decimal,
    assert_instant,
    assert_readiness_read,
    factories as f,
    fixtures as fx,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)


def _blocked_cycle_with_remediated_critical(api: ApiClient):
    """A cycle blocked by one critical deficiency whose remediation is already filed."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Fox Valley Trauma",
        state_code="WI",
        designation_level=DesignationLevel.LEVEL_I,
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-11-05T13:00:00Z",
    )
    deficiency = fx.record_deficiency(
        api,
        cycle,
        criterion_code="CD-05-13",
        deficiency_class=DeficiencyClass.TYPE_I_CRITICAL,
        remediation_due_at="2026-09-01T00:00:00Z",
    )
    fx.submit_remediation(
        api,
        cycle,
        deficiency,
        remediation_note="In-house neurosurgery call schedule signed for all 30 days.",
    )
    return center, cycle, deficiency


def _cycle_at_exactly_seventy(api: ApiClient):
    """A cycle whose readiness lands on the submission floor to the penny."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Pine Bluff Trauma",
        state_code="AR",
        designation_level=DesignationLevel.LEVEL_II,
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-10-15T13:00:00Z",
    )
    fx.deficiencies_of_class(
        api,
        cycle,
        ["CD-09-01", "CD-09-02"],
        deficiency_class=DeficiencyClass.TYPE_II_MAJOR,
        remediation_due_at="2026-09-30T00:00:00Z",
    )
    return center, cycle


def _cycle_under_review_with_one_critical(api: ApiClient):
    """A cycle deliberating with a single critical finding on the record."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Harbor Point Trauma",
        state_code="ME",
        designation_level=DesignationLevel.LEVEL_II,
    )
    cycle = fx.cycle_under_review(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-10-20T13:00:00Z",
        surveyor_user_id=SURVEYOR_1,
        window_start="2026-10-20T08:00:00Z",
        window_end="2026-10-20T17:00:00Z",
    )
    deficiency = fx.record_deficiency(
        api,
        cycle,
        criterion_code="CD-11-04",
        deficiency_class=DeficiencyClass.TYPE_I_CRITICAL,
        remediation_due_at="2026-09-15T00:00:00Z",
    )
    return center, cycle, deficiency


class TestPrepBlockedRoundTrip:
    """The cycle can re-enter a state it has already left, at a different score."""

    def test_closing_the_critical_deficiency_returns_the_cycle_to_prep(
        self, api: ApiClient
    ) -> None:
        """The cycle sits blocked at 67.00 and returns to PREP at 82.00.

        Design: Difficulty/non_linear_state_machine/verification_cycle_returns_from_prep_blocked_to_prep
        """
        _, cycle, deficiency = _blocked_cycle_with_remediated_critical(api)

        blocked = fx.get_cycle(api, cycle["id"])
        assert blocked["status"] == CycleStatus.PREP_BLOCKED
        assert_decimal(blocked["readiness_score"], 67.00, "readiness_score")

        fx.close_deficiency(api, cycle, deficiency)

        released = fx.get_cycle(api, cycle["id"])
        assert released["status"] == CycleStatus.PREP
        assert_decimal(released["readiness_score"], 82.00, "readiness_score")

    def test_the_release_clears_both_the_counter_and_the_center_posture(
        self, api: ApiClient
    ) -> None:
        """Closing the deficiency stamps it and returns the center to READY.

        Design: Difficulty/non_linear_state_machine/verification_cycle_returns_from_prep_blocked_to_prep
        """
        center, cycle, deficiency = _blocked_cycle_with_remediated_critical(api)

        fx.close_deficiency(api, cycle, deficiency)

        assert fx.get_cycle(api, cycle["id"])["open_type_i_count"] == 0

        closed = fx.get_deficiency(api, cycle["id"], deficiency["id"])
        assert closed["status"] == DeficiencyStatus.CLOSED
        assert_instant(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

        after_center = fx.get_center(api, center["id"])
        assert after_center["open_critical_deficiency_count"] == 0
        assert after_center["readiness_posture"] == ReadinessPosture.READY


class TestSubmissionFloor:
    """The submission gate admits a score that sits exactly on its floor."""

    def test_a_score_of_exactly_seventy_is_accepted_for_submission(
        self, api: ApiClient
    ) -> None:
        """Two major deficiencies and the full national outreach gap still submit.

        Design: Difficulty/boundary_precision_check/submit_accepted_when_readiness_lands_exactly_on_seventy
        """
        center, cycle = _cycle_at_exactly_seventy(api)
        assert_decimal(
            fx.get_cycle(api, cycle["id"])["readiness_score"], 70.00, "readiness_score"
        )

        response = api.submit_verification_cycle(
            cycle["id"], make_trauma_program_manager_headers(center["id"])
        )
        submitted = validate_success(response, 200)
        assert submitted["status"] == CycleStatus.SUBMITTED
        assert_decimal(submitted["readiness_score"], 70.00, "readiness_score")

    def test_the_accepted_submission_leaves_the_deficiency_counters_intact(
        self, api: ApiClient
    ) -> None:
        """Submission is not a remediation: the two major findings are still open.

        Design: Difficulty/boundary_precision_check/submit_accepted_when_readiness_lands_exactly_on_seventy
        """
        center, cycle = _cycle_at_exactly_seventy(api)

        fx.submit_cycle(api, cycle)

        after = fx.get_cycle(api, cycle["id"])
        assert after["open_type_ii_count"] == 2
        assert after["open_type_i_count"] == 0
        assert fx.get_center(api, center["id"])["readiness_posture"] == ReadinessPosture.READY


class TestVerifiedDecisionGate:
    """A decision is gated by an aggregate over the cycle's own child findings."""

    def test_an_open_critical_finding_blocks_the_verified_decision(
        self, api: ApiClient
    ) -> None:
        """Remediation alone does not clear the block; the counter stays at 1.

        Design: Difficulty/cross_entity_state_dependency/verified_decision_requires_zero_open_critical_deficiencies
        """
        center, cycle, deficiency = _cycle_under_review_with_one_critical(api)
        cycle_version = fx.get_cycle(api, cycle["id"])["version"]

        refused = api.decide_verification_cycle(
            cycle["id"],
            f.decide_payload(Decision.VERIFIED, "2026-11-01T00:00:00Z"),
            make_verification_reviewer_headers(),
        )
        validate_error(refused, E.CRITICAL_DEFICIENCY_BLOCKS_VERIFICATION, 409)
        assert fx.get_cycle(api, cycle["id"])["status"] == CycleStatus.UNDER_REVIEW

        fx.submit_remediation(
            api,
            cycle,
            deficiency,
            remediation_note="Trauma surgeon call schedule rebuilt with 24/7 in-house coverage.",
            expected_cycle_version=cycle_version,
        )
        assert (
            fx.get_deficiency(api, cycle["id"], deficiency["id"])["status"]
            == DeficiencyStatus.REMEDIATION_SUBMITTED
        )
        assert fx.get_cycle(api, cycle["id"])["open_type_i_count"] == 1
        assert fx.get_center(api, center["id"])["national_verification_status"] == (
            NationalVerificationStatus.NOT_VERIFIED
        )

    def test_the_same_decision_succeeds_once_the_finding_is_closed(
        self, api: ApiClient
    ) -> None:
        """The reviewer's close drops the counter to zero and the decision then lands.

        Design: Difficulty/cross_entity_state_dependency/verified_decision_requires_zero_open_critical_deficiencies
        """
        center, cycle, deficiency = _cycle_under_review_with_one_critical(api)
        cycle_version = fx.get_cycle(api, cycle["id"])["version"]

        validate_error(
            api.decide_verification_cycle(
                cycle["id"],
                f.decide_payload(Decision.VERIFIED, "2026-11-01T00:00:00Z"),
                make_verification_reviewer_headers(),
            ),
            E.CRITICAL_DEFICIENCY_BLOCKS_VERIFICATION,
            409,
        )

        fx.submit_remediation(
            api,
            cycle,
            deficiency,
            remediation_note="Trauma surgeon call schedule rebuilt with 24/7 in-house coverage.",
            expected_cycle_version=cycle_version,
        )
        fx.close_deficiency(api, cycle, deficiency)
        assert (
            fx.get_deficiency(api, cycle["id"], deficiency["id"])["status"]
            == DeficiencyStatus.CLOSED
        )
        assert fx.get_cycle(api, cycle["id"])["open_type_i_count"] == 0

        accepted = api.decide_verification_cycle(
            cycle["id"],
            f.decide_payload(Decision.VERIFIED, "2026-11-01T00:00:00Z"),
            make_verification_reviewer_headers(),
        )
        decided = validate_success(accepted, 200)
        assert decided["status"] == CycleStatus.VERIFIED

        after_center = fx.get_center(api, center["id"])
        assert (
            after_center["national_verification_status"]
            == NationalVerificationStatus.VERIFIED
        )
        assert after_center["readiness_posture"] == ReadinessPosture.READY


class TestOverdueLoopsAtSubmission:
    """Time alone can push a submittable cycle under the readiness floor."""

    def test_two_overdue_loops_drop_the_cycle_below_the_submission_threshold(
        self, api: ApiClient
    ) -> None:
        """Nothing was written between the two clock readings, yet the submission is refused.

        Design: Corner/validations/overdue_loops_drop_readiness_below_threshold_at_submit
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Overlook Trauma",
            state_code="PA",
            designation_level=DesignationLevel.LEVEL_II,
        )
        cycle = fx.create_cycle(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-12-09T13:00:00Z",
        )
        first = fx.create_pi_event(
            api,
            center["id"],
            event_type=PiEventType.TRANSFER_DELAY,
            severity=PiSeverity.MEDIUM,
        )
        second = fx.create_pi_event(
            api,
            center["id"],
            event_type=PiEventType.MORTALITY_REVIEW,
            severity=PiSeverity.MEDIUM,
        )
        for event in (first, second):
            assert_instant(
                event["loop_closure_due_at"],
                "2026-09-30T00:00:00Z",
                "loop_closure_due_at",
            )

        fx.move_clock(api, "2026-10-01T00:00:00Z")

        refused = api.submit_verification_cycle(
            cycle["id"], make_trauma_program_manager_headers(center["id"])
        )
        validate_error(refused, E.READINESS_BELOW_THRESHOLD, 409)
        for wrong in (E.POSTURE_SUSPENDED, E.INVALID_CYCLE_STATE):
            assert refused.json()["data"]["error_id"] != wrong, (
                "the readiness floor is what refuses this submission"
            )

        after = fx.get_cycle(api, cycle["id"])
        assert after["status"] == CycleStatus.PREP
        assert after["decided_at"] is None

        assert_readiness_read(
            get_success_data(
                api.get_cycle_readiness(
                    cycle["id"], make_trauma_program_manager_headers(center["id"])
                )
            ),
            None,
            deficiency_penalty=0,
            outreach_penalty=18.00,
            pi_penalty=20,
            readiness_score=62.00,
            submit_eligible=False,
        )
