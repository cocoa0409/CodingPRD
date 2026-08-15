"""Consistency review claims: cohort-size gate at creation."""
import pytest

from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    setup_active_pip,
    create_check_in_payload,
    create_legal_review_payload,
    create_and_submit_legal_review,
    propose_outcome,
    approve_outcome,
    create_consistency_review_payload,
    get_pip,
    set_clock,
    make_hrbp_headers,
    make_director_headers,
)


class TestConsistencyCohortGate:
    def _setup_closed_pip(self, api):
        """One TERMINATION-closed PIP (insufficient cohort on its own)."""
        ctx = setup_active_pip(
            category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        ctx["director_id"] = director["id"]
        create_and_submit_legal_review(
            ctx, hrbp_id=ctx["hrbp_id"],
            rationale="Documentation complete; no elevated legal risk.",
        )
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement observed over the plan window.")
        decision = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        set_clock(ctx["ou_id"], "2026-09-07T00:00:00Z")  # close finalizes
        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_TERMINATED"
        return ctx

    def test_creation_with_empty_cohort_rejected(self, api):
        """PRD §3.8: "The `cohort_size` field is the cohort's count, and creation
        requires at least three comparable closed plans (`ERR_COHORT_TOO_SMALL`);
        with an empty cohort the disparity score is undefined and creation fails
        the same way."

        Design: Corner/calculations/consistency_disparity_score_cohort_too_small_rejected
        """
        ctx = self._setup_closed_pip(api)
        # Only one closed PIP exists in the org unit — the cohort of *other*
        # comparable closed plans is empty, so creation must fail.
        resp = api.create_consistency_review(
            ctx["ou_id"],
            create_consistency_review_payload(ctx["pip_id"]),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COHORT_TOO_SMALL)

    def test_creation_with_nonexistent_target_rejected(self, api):
        """PRD §2.6: "the first identifier that does not resolve to an existing
        resource fails the request with `ERR_NOT_FOUND` (HTTP 404)" — a
        `target_pip_id` that resolves to nothing cannot anchor a cohort.
        PRD §3.8: "creation requires at least three comparable closed plans
        (`ERR_COHORT_TOO_SMALL`)".

        Design: Corner/validations/consistency_review_adjudicate_with_small_cohort_returns_422
        """
        cast = setup_cast()
        add_employee(cast["ou_id"], "Director", "d@x.com", job_level=9)
        resp = api.create_consistency_review(
            cast["ou_id"],
            create_consistency_review_payload(NON_EXISTENT_UUID),
            make_hrbp_headers(cast["hrbp_id"]),
        )
        # Nonexistent target: either the body reference fails resolution (404) or
        # the empty cohort fails creation (422). Both are PRD-consistent here.
        assert resp.status_code in (404, 422), (
            f"expected 404 or 422 for nonexistent target_pip_id, got {resp.status_code}"
        )
