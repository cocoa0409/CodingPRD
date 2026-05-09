"""Quarterly review chain: self / manager / calibration / lock (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    self_submit_payload, manager_submit_payload, calibrate_payload,
    setup_review_at_pending_self,
    setup_review_at_pending_manager,
    setup_review_at_pending_calibration,
    create_user, make_manager_headers, make_employee_headers,
)


# ---------------------------------------------------------------------------
# Difficulty-design: non_linear_state_machine/review_score_revision_cycle
# ---------------------------------------------------------------------------

class TestReviewRevisionCycle:
    """# difficulty: non_linear_state_machine/review_score_revision_cycle"""

    def test_self_submit_advances_pending_self_to_pending_manager(self, api):
        """PRD §3.7: "the system records `self_submitted_at`, and the review advances `PENDING_SELF → PENDING_MANAGER`".

        Claim: self-submit with self_score=0.6 → status=PENDING_MANAGER, self_score=0.6,
        self_submitted_at != null, revision_count=0.
        # difficulty: non_linear_state_machine/review_score_revision_cycle
        """
        s = setup_review_at_pending_self()
        resp = api.self_submit_review(
            s["review"]["id"], self_submit_payload(0.6),
            s["org"]["employee_headers"],
        )
        review = validate_success(resp)
        assert review["status"] == "PENDING_MANAGER"
        assert float(review["self_score"]) == pytest.approx(0.6, abs=1e-6)
        assert review.get("self_submitted_at") is not None
        assert review["revision_count"] == 0

    def test_manager_return_resets_self_and_increments_revision(self, api):
        """PRD §3.7: "Manager return is also a Manager-of-owner action and runs in the opposite direction: it sends the review back to the owner for revision, advancing `PENDING_MANAGER → PENDING_SELF`. The return resets `self_score` and `self_submitted_at` to null and increments `revision_count` by 1".

        Claim: from PENDING_MANAGER, manager-return → status=PENDING_SELF, self_score=null,
        self_submitted_at=null, revision_count=1.
        # difficulty: non_linear_state_machine/review_score_revision_cycle
        """
        s = setup_review_at_pending_manager(self_score=0.6)
        resp = api.manager_return_review(s["review"]["id"], s["org"]["manager_headers"])
        review = validate_success(resp)
        assert review["status"] == "PENDING_SELF"
        assert review.get("self_score") is None
        assert review.get("self_submitted_at") is None
        assert review["revision_count"] == 1

    def test_resubmit_after_revision_does_not_increment_revision_count(self, api):
        """PRD §3.7: "The return resets `self_score` and `self_submitted_at` to null and increments `revision_count` by 1".

        Claim: after manager-return (revision_count=1), owner re-submits → status=PENDING_MANAGER,
        new self_score recorded, revision_count remains 1 (only the return increments it).
        # difficulty: non_linear_state_machine/review_score_revision_cycle
        """
        s = setup_review_at_pending_manager(self_score=0.6)
        api.manager_return_review(s["review"]["id"], s["org"]["manager_headers"])
        resp = api.self_submit_review(
            s["review"]["id"], self_submit_payload(0.7),
            s["org"]["employee_headers"],
        )
        review = validate_success(resp)
        assert review["status"] == "PENDING_MANAGER"
        assert float(review["self_score"]) == pytest.approx(0.7, abs=1e-6)
        assert review["revision_count"] == 1


# ---------------------------------------------------------------------------
# Manager-of-owner check
# ---------------------------------------------------------------------------

class TestManagerOfOwner:
    def test_manager_submit_by_unrelated_manager_returns_err_not_manager_of_owner(self, api):
        """PRD §3.7: "Manager submission is performed by the direct manager of the objective owner — that is, the `Manager` whose `User.id` equals `User.manager_id` of the objective owner. Any other Manager sees `ERR_NOT_MANAGER_OF_OWNER`."

        Claim: manager-submit by a Manager whose id != owner.manager_id → ERR_NOT_MANAGER_OF_OWNER.
        """
        s = setup_review_at_pending_manager(self_score=0.6)
        # Create another manager not in the owner's manager chain
        other_mgr = create_user(s["org"]["department"]["id"], role_type="MANAGER")
        other_mgr_headers = make_manager_headers(other_mgr["id"])
        resp = api.manager_submit_review(
            s["review"]["id"], manager_submit_payload(0.5), other_mgr_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_MANAGER_OF_OWNER.value)

    def test_manager_submit_by_correct_manager_succeeds(self, api):
        """PRD §3.7: "Manager submission is performed by the direct manager of the objective owner".

        Claim: manager whose id == owner.manager_id → submit succeeds, status=PENDING_CALIBRATION.
        """
        s = setup_review_at_pending_manager(self_score=0.6)
        resp = api.manager_submit_review(
            s["review"]["id"], manager_submit_payload(0.5), s["org"]["manager_headers"]
        )
        review = validate_success(resp)
        assert review["status"] == "PENDING_CALIBRATION"
        assert float(review["manager_score"]) == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# Difficulty-design: boundary_precision_check/calibration_delta_strict_greater_than_boundary
# ---------------------------------------------------------------------------

class TestCalibrationDeltaBoundary:
    """# difficulty: boundary_precision_check/calibration_delta_strict_greater_than_boundary"""

    def test_calibration_delta_exactly_005_rejected(self, api):
        """PRD §3.7: "the request is rejected with `ERR_DELTA_TOO_SMALL` unless the absolute difference between `calibration_score` and `manager_score` is **strictly greater than** five-hundredths (0.05) — a calibration that exactly equals the manager's score, or that differs by at most 0.05, fails this check".

        Claim: manager_score=0.5; calibration_score=0.55; delta=0.05 EXACTLY → ERR_DELTA_TOO_SMALL.
        # difficulty: boundary_precision_check/calibration_delta_strict_greater_than_boundary
        """
        s = setup_review_at_pending_calibration(self_score=0.6, manager_score=0.5)
        resp = api.calibrate_review(
            s["review"]["id"], calibrate_payload(0.55), s["org"]["hrbp_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_DELTA_TOO_SMALL.value)

    def test_calibration_delta_above_005_accepted(self, api):
        """PRD §3.7: "strictly greater than five-hundredths (0.05)".

        Claim: manager_score=0.5; calibration_score=0.5501; delta=0.0501 > 0.05 → succeeds.
        # difficulty: boundary_precision_check/calibration_delta_strict_greater_than_boundary
        """
        s = setup_review_at_pending_calibration(self_score=0.6, manager_score=0.5)
        resp = api.calibrate_review(
            s["review"]["id"], calibrate_payload(0.5501), s["org"]["hrbp_headers"]
        )
        review = validate_success(resp)
        assert float(review["calibration_score"]) == pytest.approx(0.5501, abs=1e-6)


# ---------------------------------------------------------------------------
# Lock: final_score precedence, with and without calibration
# ---------------------------------------------------------------------------

class TestLockFinalScore:
    def test_lock_without_calibration_uses_manager_score(self, api):
        """PRD §3.7: "if `calibration_score` is non-null, `final_score` equals `calibration_score`; otherwise it equals `manager_score`."

        Claim: no calibration; lock → final_score == manager_score.
        """
        s = setup_review_at_pending_calibration(self_score=0.6, manager_score=0.5)
        resp = api.lock_review(s["review"]["id"], s["org"]["hrbp_headers"])
        review = validate_success(resp)
        assert review["status"] == "LOCKED"
        assert float(review["final_score"]) == pytest.approx(0.5, abs=1e-6)

    def test_lock_with_calibration_uses_calibration_score(self, api):
        """PRD §3.7: "if `calibration_score` is non-null, `final_score` equals `calibration_score`".

        Claim: calibration=0.4; lock → final_score == 0.4.
        """
        s = setup_review_at_pending_calibration(self_score=0.6, manager_score=0.5)
        api.calibrate_review(s["review"]["id"], calibrate_payload(0.4),
                             s["org"]["hrbp_headers"])
        resp = api.lock_review(s["review"]["id"], s["org"]["hrbp_headers"])
        review = validate_success(resp)
        assert review["status"] == "LOCKED"
        assert float(review["final_score"]) == pytest.approx(0.4, abs=1e-6)

    def test_lock_cascades_objective_to_locked(self, api):
        """PRD §3.7: "the cascade transitions the parent `Objective.status` from `IN_REVIEW` to `LOCKED` and copies `ReviewScore.final_score` onto `Objective.final_score`."

        Claim: after lock → Objective.status=LOCKED, Objective.final_score=ReviewScore.final_score.
        """
        s = setup_review_at_pending_calibration(self_score=0.6, manager_score=0.5)
        api.calibrate_review(s["review"]["id"], calibrate_payload(0.4),
                             s["org"]["hrbp_headers"])
        api.lock_review(s["review"]["id"], s["org"]["hrbp_headers"])
        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        assert obj["status"] == "LOCKED"
        assert float(obj["final_score"]) == pytest.approx(0.4, abs=1e-6)
