"""Cycle lifecycle: lock-reviews -> IN_CALIBRATION; calibration commit
-> COMP_PLANNING; close -> CLOSED. The close cascade writes back
to Employee fields (base_salary_cents, equity_units_outstanding,
job_level).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    approve_plan,
    create_comp_plan_payload,
    propose_plan,
    setup_draft_comp_plan,
    setup_finalized_review_case,
    submit_review_case,
    setup_submittable_review_case,
    validate_error,
    validate_success,
)


# ===========================================================================
# Lock-reviews: OPEN -> IN_CALIBRATION + cascade SUBMITTED -> LOCKED
# ===========================================================================
class TestLockReviews:

    def test_lock_reviews_advances_cycle_and_locks_cases(self, api):
        """PRD §3.2: "The cycle moves to `IN_CALIBRATION` when an HRBP
        locks reviews:...the cascade carries every `SUBMITTED` case to
        `LOCKED`, refreshes the cycle's `updated_at`, and bumps its
        `version`."."""
        bundle = submit_review_case(setup_submittable_review_case())
        cyc = validate_success(api.lock_reviews(
            bundle.cycle["id"], bundle.hrbp.headers,
        ), 200)
        assert cyc["status"] == "IN_CALIBRATION"
        rc = validate_success(api.get_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.hrbp.headers,
        ), 200)
        assert rc["status"] == "LOCKED"


# ===========================================================================
# Close cycle: COMP_PLANNING -> CLOSED + Employee cascade
# ===========================================================================
class TestCloseCycleCascade:

    def test_close_applies_merit_to_employee_base_salary(self, api):
        """PRD §3.2: "Closure is itself a cascade: every `APPROVED`
        `CompPlan` with `merit_increase_cents` greater than zero adds
        that amount to the subject's `base_salary_cents`...".
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_base_salary_cents=10_000_000,
            subject_job_level=4,
        )
        propose_plan(bundle)
        approve_plan(bundle)
        merit = bundle.comp_plan["merit_increase_cents"]
        before = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        validate_success(api.close_cycle(
            bundle.cycle["id"], bundle.hrbp.headers,
        ), 200)
        after = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert after["base_salary_cents"] == before["base_salary_cents"] + merit

    def test_close_applies_equity_to_employee_units_outstanding(self, api):
        """PRD §3.2: "every plan with `equity_refresh_units` greater
        than zero adds those units to the subject's
        `equity_units_outstanding`..."."""
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="MEETS",
            subject_job_level=4,
        )
        propose_plan(bundle)
        approve_plan(bundle)
        equity = bundle.comp_plan["equity_refresh_units"]
        before = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        validate_success(api.close_cycle(
            bundle.cycle["id"], bundle.hrbp.headers,
        ), 200)
        after = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert after["equity_units_outstanding"] == (
            before["equity_units_outstanding"] + equity
        )

    def test_close_rejected_when_plan_still_proposed(self, api):
        """PRD §3.2: "an HRBP closes the cycle, transitioning it to
        `CLOSED`, but only after every `CompPlan` on the cycle is in
        `APPROVED` or `REJECTED`...".
        """
        bundle = setup_draft_comp_plan(final_rating="MEETS")
        propose_plan(bundle)  # PROPOSED, neither approved nor rejected.
        res = api.close_cycle(bundle.cycle["id"], bundle.hrbp.headers)
        # PRD §3.2 names the precondition but does not pin a specific
        # error_id; accept ERR_INVALID_STATE (the natural state
        # precondition violation) or another 4xx.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_INVALID_STATE"])

    def test_close_applies_promotion_to_job_level(self, api):
        """PRD §3.2: "every plan with `promotion_to_level` set
        rewrites the subject's `job_level` to that value."."""
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_job_level=4,
            promotion_to_level=5,
        )
        propose_plan(bundle)
        approve_plan(bundle)
        before = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert before["job_level"] == 4
        validate_success(api.close_cycle(
            bundle.cycle["id"], bundle.hrbp.headers,
        ), 200)
        after = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert after["job_level"] == 5


# ===========================================================================
# Cross-entity state dependency: ReviewCase requires Cycle.status == OPEN
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_patch_review_case_when_cycle_not_open(self, api):
        """PRD §3.3: "once the cycle leaves `OPEN`, any further mutation
        on those child resources is rejected with `ERR_CYCLE_NOT_OPEN`."

        # difficulty: cross_entity_state_dependency/review_case_submit_requires_cycle_open
        """
        bundle = submit_review_case(setup_submittable_review_case())
        # Lock the cycle: moves OPEN -> IN_CALIBRATION; the case
        # cascades SUBMITTED -> LOCKED.
        bundle.cycle = validate_success(api.lock_reviews(
            bundle.cycle["id"], bundle.hrbp.headers,
        ), 200)
        assert bundle.cycle["status"] == "IN_CALIBRATION"
        # Now PATCH on a (now LOCKED) child resource: PRD §3.3 says any
        # mutation on child resources is rejected with ERR_CYCLE_NOT_OPEN.
        res = api.update_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            {"manager_rating": "MEETS"},
            bundle.manager.headers,
        )
        validate_error(res, "ERR_CYCLE_NOT_OPEN")
