"""Plan-review correction cycle: the UNDER_REVIEW -> CORRECTIONS_REQUIRED ->
UNDER_REVIEW back-edge with review_cycle increment, the zero-open-corrections
resubmit gate, the assigned-reviewer ownership check vs open-corrections
precedence, idempotent correction resolution, and attach-to-completed-review.

PRD §3.4 (correction cycle), §2.6 (validation order).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_permit_corrections_required,
    create_approved_permit,
    create_plan_reviewer,
    make_reviewer_headers,
    make_applicant_headers,
    api_client as _client,
)


class TestCyclicReviewLoop:
    def test_resubmit_reenters_review_and_increments_cycle(self, api):
        """PRD §3.4: "Resubmitting increments the permit's `review_cycle` by one,
        opens a fresh `PlanReview` (with `review_status` `OPEN`, `decision`
        `PENDING`, and `cycle_number` equal to the new `review_cycle`), moves the
        permit from `CORRECTIONS_REQUIRED` back to `UNDER_REVIEW`, appends a
        `RESUBMITTED` audit event, and bumps the version."

        Design: Difficulty/non_linear_state_machine/permit_cyclic_corrections_review_loop
        """
        permit, review, reviewer, corrections = create_permit_corrections_required(
            num_open_corrections=1, work_class="ALTERATION",
            fee_method="VALUATION", declared_valuation=100000)
        # Resolve the single open correction, then resubmit.
        validate_success(api.resolve_correction_notice(
            corrections[0]["id"], make_applicant_headers()))
        resp = api.resubmit_permit(permit["id"], make_applicant_headers())
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"
        assert data["review_cycle"] == 1

    def test_resubmit_creates_fresh_open_review_for_new_cycle(self, api):
        """PRD §3.4: "opens a fresh `PlanReview` (with `review_status` `OPEN`,
        `decision` `PENDING`, and `cycle_number` equal to the new `review_cycle`)".

        Design: Difficulty/non_linear_state_machine/permit_cyclic_corrections_review_loop
        """
        permit, review, reviewer, corrections = create_permit_corrections_required(
            num_open_corrections=1, work_class="ALTERATION",
            fee_method="VALUATION", declared_valuation=100000)
        validate_success(api.resolve_correction_notice(
            corrections[0]["id"], make_applicant_headers()))
        validate_success(api.resubmit_permit(permit["id"], make_applicant_headers()))
        reviews, _meta = _list_reviews_for_permit(api, permit["id"])
        open_reviews = [r for r in reviews if r["review_status"] == "OPEN"]
        assert len(open_reviews) == 1
        assert open_reviews[0]["cycle_number"] == 1
        assert open_reviews[0]["decision"] == "PENDING"


class TestResubmitZeroCorrectionsGate:
    def test_resubmit_with_open_correction_rejected(self, api):
        """PRD §3.4: "Resubmission is permitted only while the permit's `status`
        is `CORRECTIONS_REQUIRED` and its `open_correction_count` is zero ... a
        resubmission with any open correction remaining is rejected with
        `ERR_OPEN_CORRECTIONS`."

        Design: Difficulty/boundary_precision_check/resubmit_requires_zero_open_corrections_empty_set_edge
        """
        permit, review, reviewer, corrections = create_permit_corrections_required(
            num_open_corrections=1, work_class="ALTERATION",
            fee_method="VALUATION", declared_valuation=100000)
        permit_read = validate_success(api.get_permit(permit["id"], make_applicant_headers()))
        assert permit_read["open_correction_count"] == 1
        resp = api.resubmit_permit(permit["id"], make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_OPEN_CORRECTIONS.value)

    def test_resubmit_succeeds_only_when_count_reaches_zero(self, api):
        """PRD §3.4: "Resubmission is permitted only while the permit's `status`
        is `CORRECTIONS_REQUIRED` and its `open_correction_count` is zero — that
        is, every correction notice on the latest review has been resolved".

        Design: Difficulty/boundary_precision_check/resubmit_requires_zero_open_corrections_empty_set_edge
        """
        permit, review, reviewer, corrections = create_permit_corrections_required(
            num_open_corrections=1, work_class="ALTERATION",
            fee_method="VALUATION", declared_valuation=100000)
        validate_success(api.resolve_correction_notice(
            corrections[0]["id"], make_applicant_headers()))
        permit_read = validate_success(api.get_permit(permit["id"], make_applicant_headers()))
        assert permit_read["open_correction_count"] == 0
        resp = api.resubmit_permit(permit["id"], make_applicant_headers())
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"


class TestReviewerOwnershipPrecedence:
    def test_wrong_reviewer_masks_open_corrections_on_decide(self, api):
        """PRD §2.6: "Among the business rules themselves the relative order is:
        the assigned-reviewer ownership check (`ERR_NOT_ASSIGNED_REVIEWER`), the
        segregation-of-duties check ... the open-corrections gate
        (`ERR_OPEN_CORRECTIONS`)".
        PRD §3.4: "The acting `PlanReviewer` must be the review's own `reviewer_id`;
        a decision attempted by any other reviewer is rejected with
        `ERR_NOT_ASSIGNED_REVIEWER`."

        Design: Difficulty/priority_pair_validation_conflict/not_assigned_reviewer_beats_open_corrections_on_decide
        """
        # Permit UNDER_REVIEW owned by rev1 with one OPEN correction; rev2 attempts APPROVED.
        rev1 = create_plan_reviewer()
        rev2 = create_plan_reviewer()
        permit, review, _rev = _under_review_with_open_correction(api, rev1)
        resp = api.decide_review(review["id"], {"decision": "APPROVED"},
                                 make_reviewer_headers(rev2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER.value)

    def test_wrong_reviewer_decide_returns_403(self, api):
        """PRD §3.4: "a decision attempted by any other reviewer is rejected with
        `ERR_NOT_ASSIGNED_REVIEWER`."

        Design: Difficulty/priority_pair_validation_conflict/not_assigned_reviewer_beats_open_corrections_on_decide
        """
        rev1 = create_plan_reviewer()
        rev2 = create_plan_reviewer()
        permit, review, _rev = _under_review_with_open_correction(api, rev1)
        resp = api.decide_review(review["id"], {"decision": "APPROVED"},
                                 make_reviewer_headers(rev2["id"]))
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}"


class TestCorrectionResolutionIdempotency:
    def test_resolve_correction_twice_second_fails(self, api):
        """PRD §3.4: "resolution is permitted only while the notice's
        `item_status` is `OPEN` and the parent permit's `status` is
        `CORRECTIONS_REQUIRED`."

        Design: Corner/state_machines/resolve_correction_twice_idempotency_second_fails
        """
        permit, review, reviewer, corrections = create_permit_corrections_required(
            num_open_corrections=1, work_class="ALTERATION",
            fee_method="VALUATION", declared_valuation=100000)
        validate_success(api.resolve_correction_notice(
            corrections[0]["id"], make_applicant_headers()))
        resp = api.resolve_correction_notice(corrections[0]["id"], make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCorrectionAttachState:
    def test_attach_to_completed_review_rejected(self, api):
        """PRD §3.4: "A `PlanReviewer` attaches a notice to a review whose
        `review_status` is `OPEN` — attaching to a review that is not open is
        rejected with `ERR_INVALID_STATE`".

        Design: Corner/validations/correction_attach_on_completed_review_invalid_state
        """
        # APPROVED decision completes the review; attaching afterward must fail.
        permit, review, reviewer = create_approved_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        resp = api.create_correction_notice(
            review["id"], {"code_section": "R311.1", "description": "late notice"},
            make_reviewer_headers(reviewer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── local helpers ─────────────────────────────────────
def _list_reviews_for_permit(api, permit_id):
    resp = api.list_reviews(make_applicant_headers(), params={"permit_id": permit_id})
    body = resp.json()
    return body.get("data", []), body.get("meta", {})


def _under_review_with_open_correction(api, reviewer):
    """Permit UNDER_REVIEW owned by `reviewer` with exactly one OPEN correction notice."""
    from test_helpers import create_permit_under_review, attach_correction
    permit, review, _rev = create_permit_under_review(
        reviewer=reviewer, work_class="ALTERATION",
        fee_method="VALUATION", declared_valuation=100000)
    attach_correction(review["id"], reviewer["id"],
                      code_section="R302.1", description="Fire separation missing")
    return permit, review, reviewer
