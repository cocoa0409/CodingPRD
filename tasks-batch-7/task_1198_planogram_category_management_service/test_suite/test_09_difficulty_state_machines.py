"""Difficulty: non_linear_state_machine — cyclic planogram; branching product."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    make_category_captain_headers,
    setup_category_with_listed_product,
    setup_draft_planogram_with_line,
    setup_planogram_in_review,
    validate_error,
    validate_success,
)


class TestPlanogramCyclicDraftReviewLoop:
    def test_planogram_full_cycle_returns_to_draft(self, api, category_manager_headers):
        """PRD §3.5: "Authors are not trapped by a single submission. A
        `CategoryCaptain` may return an `IN_REVIEW` planogram to `DRAFT` at
        will, and may likewise return an `APPROVED` planogram to `DRAFT`
        provided the planogram has never been `ACTIVE` — so the cycle `DRAFT`
        → `IN_REVIEW` → `DRAFT` can iterate indefinitely until the planogram
        is finally approved or rejected."

        Design: Difficulty/non_linear_state_machine/planogram_cyclic_draft_review_loop
        """
        retailer, category, supplier, product, pg, line = setup_planogram_in_review()
        rid, cid, pgid, sid = retailer["id"], category["id"], pg["id"], supplier["id"]
        captain_headers = make_category_captain_headers(sid)
        # IN_REVIEW → DRAFT
        validate_success(api.return_planogram_to_draft(rid, cid, pgid, captain_headers))
        # DRAFT → IN_REVIEW again
        validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
        # IN_REVIEW → DRAFT again
        final = validate_success(api.return_planogram_to_draft(rid, cid, pgid, captain_headers))
        assert final["status"] == "DRAFT"

    def test_planogram_version_increments_through_cycle(self, api, category_manager_headers):
        """PRD §2.4: "`version` — an integer that starts low at creation and
        increments by one on every mutation, including mutations driven by
        derived-value recomputation or cascading side effects rather than by
        a direct client write."

        Design: Difficulty/non_linear_state_machine/planogram_cyclic_draft_review_loop
        """
        retailer, category, supplier, product, pg, line = setup_planogram_in_review()
        rid, cid, pgid, sid = retailer["id"], category["id"], pg["id"], supplier["id"]
        captain_headers = make_category_captain_headers(sid)
        # pg is now IN_REVIEW with some version V_after_submit.
        # Walk: return-to-draft, submit, return-to-draft.
        v0 = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))["version"]
        validate_success(api.return_planogram_to_draft(rid, cid, pgid, captain_headers))
        v1 = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))["version"]
        validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
        v2 = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))["version"]
        final = validate_success(api.return_planogram_to_draft(rid, cid, pgid, captain_headers))
        v3 = final["version"]
        assert v1 > v0
        assert v2 > v1
        assert v3 > v2
        assert final["status"] == "DRAFT"


class TestProductBranchingFlow:
    def test_discontinue_then_cancel_returns_to_listed(self, api, category_manager_headers):
        """PRD §3.3: "Products already in flight get one mercy: while the
        effective date is still in the future, a `CategoryManager` may cancel
        the discontinuation, returning the product to `LISTED` and clearing
        `discontinuation_effective_date`."

        Design: Difficulty/non_linear_state_machine/product_branching_cut_in_discontinue_relist
        """
        retailer, category, supplier, product = setup_category_with_listed_product(
            product_overrides={"weekly_demand_units": 50}
        )
        rid, pid = retailer["id"], product["id"]
        pv = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        validate_success(
            api.discontinue_product(
                rid, pid,
                {"discontinuation_effective_date": "2027-01-01T00:00:00Z", "expected_product_version": pv},
                category_manager_headers,
            )
        )
        final = validate_success(api.cancel_discontinuation(rid, pid, category_manager_headers))
        assert final["status"] == "LISTED"
        assert final["discontinuation_effective_date"] is None

    def test_branching_side_effect_cancel_does_not_delete_draft_lines(
        self, api, category_manager_headers
    ):
        """PRD §3.3: "Products already in flight get one mercy: while the
        effective date is still in the future, a `CategoryManager` may cancel
        the discontinuation, returning the product to `LISTED` and clearing
        `discontinuation_effective_date`."
        PRD §3.3 distinguishes cancel-discontinuation (no cascade) from the
        clock-driven delisting path ("every planogram line referencing the
        product on a `DRAFT` or `IN_REVIEW` planogram is deleted outright").

        Design: Difficulty/non_linear_state_machine/product_branching_cut_in_discontinue_relist
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line(
            product_overrides={"weekly_demand_units": 50}
        )
        rid, cid, pgid, pid, lid = (
            retailer["id"], category["id"], pg["id"], product["id"], line["id"],
        )
        pv = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        validate_success(
            api.discontinue_product(
                rid, pid,
                {"discontinuation_effective_date": "2027-01-01T00:00:00Z", "expected_product_version": pv},
                category_manager_headers,
            )
        )
        validate_success(api.cancel_discontinuation(rid, pid, category_manager_headers))
        # The line on the DRAFT planogram must still exist (cancel path has no cascade).
        line_now = validate_success(
            api.get_planogram_line(rid, cid, pgid, lid, category_manager_headers)
        )
        assert line_now["id"] == lid
