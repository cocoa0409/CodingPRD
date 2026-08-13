"""Facilitator pipeline, supervision gating, and capacity score (PRD §3.2)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_facilitator_to_practice,
    assert_facilitator,
    create_supervision_review_payload,
    create_training_completion_payload,
    get_success_data,
    make_active_group,
    make_bootstrap_reviewer,
    make_certified_facilitator,
    make_course,
    make_facilitator,
    make_facilitator_headers,
    make_program,
    make_room,
    make_scheduled_session,
    reset_clock,
    validate_error,
    validate_success,
)


class TestFacilitatorTerminalStates:
    def test_rejected_facilitator_is_terminal(self, api):
        """PRD §3.2: "an admin may instead reject an applicant in `SCREENING`,
        landing in `REJECTED`. `WITHDRAWN` and `REJECTED` are terminal."
        PRD §2.10: "A state-transition attempted from a state that does not
        permit it is always reported as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/facilitator_rejected_is_terminal
        """
        reset_clock()
        facilitator = make_facilitator(full_name="F")
        get_success_data(api.advance_to_screening(facilitator["id"], ADMIN))
        rejected = validate_success(api.reject_facilitator(facilitator["id"], ADMIN))
        assert rejected["status"] == "REJECTED"

        resp = api.advance_to_training(facilitator["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_facilitator(facilitator["id"], ADMIN))
        assert after["status"] == "REJECTED"


class TestCertifiedSuspendedCertifiedCycle:
    def _certify_facilitator(self, api):
        reviewer, _ = make_bootstrap_reviewer()
        facilitator = make_certified_facilitator(reviewer["id"], full_name="F")
        return facilitator, reviewer

    def test_cycle_sets_fresh_certified_at_on_reinstate(self, api):
        """PRD §3.2: "Reinstatement from `SUSPENDED` back to `CERTIFIED`
        requires at least one SupervisionReview created after the suspension
        with a `rating` of at least 4, and sets `certified_at` to the current
        time again."
        PRD §3.2: "on certification `certified_at` is set to the current time
        and `supervision_required` is set to false."

        Design: Difficulty/non_linear_state_machine/facilitator_certified_suspended_certified_cycle
        """
        reset_clock("2026-08-01T00:00:00Z")
        facilitator, reviewer = self._certify_facilitator(api)

        # Re-certify at a known clock reading to pin the first certified_at.
        reset_clock("2026-08-01T10:00:00Z")
        facilitator = validate_success(api.get_facilitator(facilitator["id"], ADMIN))
        assert facilitator["status"] == "CERTIFIED"
        cert1_at = facilitator["certified_at"]
        assert cert1_at is not None

        reset_clock("2026-08-05T10:00:00Z")
        suspended = validate_success(api.suspend_facilitator(facilitator["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"

        reset_clock("2026-08-10T10:00:00Z")
        get_success_data(api.create_supervision_review(
            facilitator["id"],
            create_supervision_review_payload(
                reviewer["id"], occurred_at="2026-08-09T00:00:00Z", rating=4),
            ADMIN))
        reinstated = validate_success(api.reinstate_facilitator(facilitator["id"], ADMIN))
        assert reinstated["status"] == "CERTIFIED"
        cert2_at = reinstated["certified_at"]
        assert cert2_at is not None and cert2_at != cert1_at, (
            "reinstatement must set certified_at to the current time again")
        assert cert2_at.startswith("2026-08-10T10:00:00"), (
            f"certified_at on reinstate must be the logical clock time, got {cert2_at}")

    def test_suspend_clears_certified_at_and_reinstate_needs_new_review(self, api):
        """PRD §3.2: "An admin may suspend a `CERTIFIED` facilitator, which
        clears `certified_at` and blocks any new session assignments."
        PRD §3.2: "Reinstatement from `SUSPENDED` back to `CERTIFIED` requires
        at least one SupervisionReview created after the suspension with a
        `rating` of at least 4"
        PRD §2.10: "A state-transition attempted from a state that does not
        permit it is always reported as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/facilitator_certified_suspended_certified_cycle
        """
        reset_clock("2026-08-01T00:00:00Z")
        facilitator, reviewer = self._certify_facilitator(api)

        suspended = validate_success(api.suspend_facilitator(facilitator["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        assert suspended.get("certified_at") is None, (
            f"suspension must clear certified_at, got {suspended.get('certified_at')}")

        # The only review so far predates the suspension: reinstate must fail.
        resp = api.reinstate_facilitator(facilitator["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # A post-suspension review with rating >= 4 unlocks reinstatement.
        reset_clock("2026-08-02T00:00:00Z")
        get_success_data(api.create_supervision_review(
            facilitator["id"],
            create_supervision_review_payload(
                reviewer["id"], occurred_at="2026-08-02T00:00:00Z", rating=4),
            ADMIN))
        reinstated = validate_success(api.reinstate_facilitator(facilitator["id"], ADMIN))
        assert reinstated["status"] == "CERTIFIED"


class TestSupervisionReviewerGate:
    def test_reviewer_below_level_4_rejected(self, api):
        """PRD §3.2: "The reviewer must hold status `CERTIFIED` with a `level`
        of at least 4, evaluated using the reviewer's level at the moment the
        review is created; otherwise the review is rejected with
        `ERR_INSUFFICIENT_REVIEWER_LEVEL` (HTTP 409)."
        PRD §3.2: "Third, the raw level is 1 plus the training points plus the
        supervision bonus, and the final `level` clamps that raw value into the
        range 1 to 5 inclusive."

        Design: Corner/validations/supervision_reviewer_below_level_4_rejected
        """
        reset_clock()
        boss, _ = make_bootstrap_reviewer()
        # R: one passing completion on a level_weight-1 course -> training
        # points 1; one rating-4 review -> bonus min(2, 1 // 2) = 0; level 2.
        low_course = make_course(code="LOW-100", credit_hours=2, level_weight=1)
        reviewer_low = make_certified_facilitator(
            boss["id"], course=low_course, full_name="R Low")
        fetched = validate_success(api.get_facilitator(reviewer_low["id"], ADMIN))
        assert fetched["level"] == 2, (
            f"expected level 2 (1 + 1 training point + 0 bonus), got {fetched['level']}")

        target = make_facilitator(full_name="T")
        resp = api.create_supervision_review(
            target["id"],
            create_supervision_review_payload(
                reviewer_low["id"], occurred_at="2026-07-20T00:00:00Z", rating=5),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REVIEWER_LEVEL)


class TestCapacityScore:
    def _build_scored_facilitator(self, api):
        """Facilitator with training_hours=10 (4h + 6h passing completions),
        supervision_count=1 (one rating-4 review), sessions_led=2."""
        reset_clock()
        reviewer, _ = make_bootstrap_reviewer()
        course_4h = make_course(code="CAP-4", credit_hours=4, level_weight=2)
        course_6h = make_course(code="CAP-6", credit_hours=6, level_weight=3)
        facilitator = make_facilitator(full_name="F Cap")
        fid = facilitator["id"]
        get_success_data(api.advance_to_screening(fid, ADMIN))
        get_success_data(api.advance_to_training(fid, ADMIN))
        get_success_data(api.create_training_completion(
            fid, create_training_completion_payload(
                course_4h["id"], completed_at="2026-07-01T00:00:00Z", score=85), ADMIN))
        get_success_data(api.create_training_completion(
            fid, create_training_completion_payload(
                course_6h["id"], completed_at="2026-07-05T00:00:00Z", score=90), ADMIN))
        get_success_data(api.advance_to_practice(fid, ADMIN))
        get_success_data(api.create_supervision_review(
            fid, create_supervision_review_payload(
                reviewer["id"], occurred_at="2026-07-20T00:00:00Z", rating=4), ADMIN))
        facilitator = get_success_data(api.certify_facilitator(fid, ADMIN))

        program = make_program(name="PX", focus_area="ANXIETY")
        room = make_room(name="Rm")
        group = make_active_group(
            program["id"], name="GX", modality="IN_PERSON", base_capacity=5)
        fac_headers = make_facilitator_headers(fid)
        for start, end, clock_after in (
                ("2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z"),
                ("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z", "2026-08-02T11:30:00Z")):
            session = make_scheduled_session(
                program["id"], group["id"], fid,
                start_at=start, end_at=end, room_id=room["id"])
            reset_clock(clock_after)
            get_success_data(api.complete_session(
                program["id"], group["id"], session["id"], fac_headers))
        return facilitator

    def test_conservative_and_accelerated_variants(self, api):
        """PRD §3.2: "The conservative variant — used when the facilitator is
        being considered as primary on a group with a critical-incident
        history — is one half of the supervision count, plus three tenths of
        the training hours, plus one fifth of the sessions led, rounded half-up
        to two decimal places. The accelerated variant — used when the
        facilitator is being considered as a cofacilitator or for a new group
        launch — is one fifth of the supervision count, plus one half of the
        training hours, plus three tenths of the sessions led, rounded half-up
        to two decimal places. The computed read returns `conservative`,
        `accelerated`, and `sessions_led`."

        Design: Difficulty/dual_variant_calc/facilitator_capacity_score_conservative_vs_accelerated
        """
        facilitator = self._build_scored_facilitator(api)
        data = validate_success(api.get_capacity_score(facilitator["id"], ADMIN))
        # training_hours = 4 + 6 = 10; supervision_count = 1; sessions_led = 2
        assert data["sessions_led"] == 2
        assert data["conservative"] == pytest.approx(3.90, abs=0.01), (
            f"0.5*1 + 0.3*10 + 0.2*2 = 3.90 expected, got {data['conservative']}")
        assert data["accelerated"] == pytest.approx(5.80, abs=0.01), (
            f"0.2*1 + 0.5*10 + 0.3*2 = 5.80 expected, got {data['accelerated']}")
        assert data["conservative"] != data["accelerated"]

    def test_zero_history_scores_zero(self, api):
        """PRD §3.2: "training hours, the sum of `credit_hours` over the
        facilitator's completions with `score` at least 70; supervision count,
        the number of the facilitator's SupervisionReviews with `rating` of at
        least 3; and sessions led, the number of sessions where the facilitator
        was primary and the session reached `COMPLETED` or
        `COMPLETED_WITH_INCIDENT`."

        Design: Difficulty/dual_variant_calc/facilitator_capacity_score_conservative_vs_accelerated
        """
        reset_clock()
        facilitator = make_facilitator(full_name="F Zero")
        data = validate_success(api.get_capacity_score(facilitator["id"], ADMIN))
        assert data["sessions_led"] == 0
        assert data["conservative"] == pytest.approx(0.0, abs=0.01)
        assert data["accelerated"] == pytest.approx(0.0, abs=0.01)
