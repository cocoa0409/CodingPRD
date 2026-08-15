"""Backfill pool: provisional vs final budget accounting and conservation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_backfill_budget_invariant, ApiErrorId,
    get_child, setup_backfill_eligible, run_backfill_select,
    make_platform_admin_headers,
)

def _admin2():
    return make_platform_admin_headers("admin_2")


class TestProvisionalVsFinal:
    def test_ordered_purchase_does_not_mutate_spent(self, api):
        """PRD §3.8: "The campaign's `backfill_spent_cents` is the sum of
        `final_cost_cents` over purchases in `PURCHASED`; it starts at 0 and is
        the authoritative actual. A provisional remaining-budget projection is
        maintained alongside: the campaign's `backfill_budget_cents` minus
        `backfill_spent_cents` minus the sum of `quoted_cost_cents` over all
        purchases still in `ORDERED`."

        Design: Difficulty/dual_variant_calc/backfill_budget_provisional_vs_final
        """
        ctx = setup_backfill_eligible(num_families=1, backfill_budget_cents=10000,
                                      wish_price_cents=3000)
        purchases = run_backfill_select(ctx["campaign"]["id"], limit=10)
        assert len(purchases) == 1
        assert purchases[0]["status"] == "ORDERED"
        campaign = validate_success(
            api.get_campaign(ctx["campaign"]["id"],
                             make_platform_admin_headers("admin_1")))
        assert campaign["backfill_spent_cents"] == 0, \
            "an ORDERED purchase feeds only the provisional projection"

    def test_mark_purchased_applies_final_cost(self, api):
        """PRD §3.8: "On success the server stamps `purchased_at` and
        `final_cost_cents`, adds `final_cost_cents` to the campaign's
        `backfill_spent_cents`, moves the child from `BACKFILL_ELIGIBLE` to
        `BACKFILL_PURCHASED` (terminal)". PRD §3.8: "Quoted cost may differ from
        receipt cost, so the provisional is optimistic."

        Design: Difficulty/dual_variant_calc/backfill_budget_provisional_vs_final
        """
        ctx = setup_backfill_eligible(num_families=1, backfill_budget_cents=10000,
                                      wish_price_cents=3000)
        purchases = run_backfill_select(ctx["campaign"]["id"], limit=10)
        purchase = validate_success(api.mark_purchased(
            purchases[0]["id"], 3200, _admin2()))
        assert purchase["status"] == "PURCHASED"
        assert purchase["final_cost_cents"] == 3200
        assert purchase["purchased_at"], "mark-purchased stamps purchased_at"
        campaign = validate_success(
            api.get_campaign(ctx["campaign"]["id"],
                             make_platform_admin_headers("admin_1")))
        assert campaign["backfill_spent_cents"] == 3200, \
            "the final variant is the only one that mutates spent"
        assert get_child(ctx["children"][0]["id"])["status"] == \
            "BACKFILL_PURCHASED"


class TestBudgetConservation:
    def test_cancel_releases_provisional_reservation(self, api):
        """PRD §3.8: "An `ORDERED` purchase may instead be cancelled — `ORDERED →
        CANCELLED` — with no cascade." PRD §3.8: "The campaign's
        `backfill_spent_cents` is the sum of `final_cost_cents` over purchases in
        `PURCHASED`; it starts at 0 and is the authoritative actual."

        Design: Difficulty/compensating_invariant/backfill_budget_conserved_across_order_and_cancel
        """
        ctx = setup_backfill_eligible(num_families=2, backfill_budget_cents=10000)
        purchases = run_backfill_select(ctx["campaign"]["id"], limit=10)
        assert len(purchases) == 2
        cancelled = validate_success(api.cancel_backfill_purchase(
            purchases[0]["id"], make_platform_admin_headers("admin_1")))
        assert cancelled["status"] == "CANCELLED"
        campaign = validate_success(
            api.get_campaign(ctx["campaign"]["id"],
                             make_platform_admin_headers("admin_1")))
        assert campaign["backfill_spent_cents"] == 0, \
            "cancelling an ORDERED purchase releases its provisional reservation"

    def test_spent_adjusts_by_exactly_final_cost(self, api):
        """PRD §3.8: "On success the server stamps `purchased_at` and
        `final_cost_cents`, adds `final_cost_cents` to the campaign's
        `backfill_spent_cents`" — the remaining pool is
        `backfill_budget_cents - backfill_spent_cents`, so purchasing at a final
        cost that differs from the quote adjusts spent by exactly the final cost.

        Design: Difficulty/compensating_invariant/backfill_budget_conserved_across_order_and_cancel
        """
        ctx = setup_backfill_eligible(num_families=2, backfill_budget_cents=10000)
        purchases = run_backfill_select(ctx["campaign"]["id"], limit=10)
        assert len(purchases) == 2
        validate_success(api.cancel_backfill_purchase(
            purchases[0]["id"], make_platform_admin_headers("admin_1")))
        purchased = validate_success(api.mark_purchased(
            purchases[1]["id"], 3500, _admin2()))
        assert purchased["final_cost_cents"] == 3500
        campaign = validate_success(
            api.get_campaign(ctx["campaign"]["id"],
                             make_platform_admin_headers("admin_1")))
        assert campaign["backfill_spent_cents"] == 3500
        assert campaign["backfill_budget_cents"] - \
            campaign["backfill_spent_cents"] == 6500
        assert_backfill_budget_invariant(campaign)


class TestBudgetExceeded:
    def test_mark_purchased_over_budget_rejected(self, api):
        """PRD §3.8: "The authoritative budget check fires here: the campaign's
        `backfill_spent_cents` plus this `final_cost_cents` must not exceed
        `backfill_budget_cents`, else the mark is rejected with
        `ERR_BACKFILL_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/backfill_budget_exceeded
        """
        ctx = setup_backfill_eligible(num_families=1, backfill_budget_cents=5000,
                                      wish_price_cents=4000)
        purchases = run_backfill_select(ctx["campaign"]["id"], limit=10)
        assert len(purchases) == 1
        res = api.mark_purchased(purchases[0]["id"], 6000, _admin2())
        validate_error(res, ApiErrorId.ERR_BACKFILL_BUDGET_EXCEEDED,
                       expected_status=422)
        campaign = validate_success(
            api.get_campaign(ctx["campaign"]["id"],
                             make_platform_admin_headers("admin_1")))
        assert campaign["backfill_spent_cents"] == 0, \
            "a rejected mark-purchased leaves spent untouched"
