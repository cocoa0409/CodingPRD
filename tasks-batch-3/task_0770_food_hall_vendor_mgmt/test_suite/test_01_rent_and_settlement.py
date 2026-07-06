"""Rent-settlement arithmetic: the provisional/final dual variant, the nested
min/max total formula, round-then-sum proration, the breakpoint boundary, the
finalize->void ledger invariant, and the finalize terminal lockdown.

All tests build their own state from scratch via test_helpers fixtures.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    open_stall, place_accepted_order, place_fulfilled_order,
    create_provisional_settlement, TEST_USERS, api_client,
)

HM = TEST_USERS["hall_manager_headers"]


class TestRentDualVariant:
    """dual_variant_calc / rent_settlement_provisional_vs_final."""

    def test_provisional_variant_counts_accepted_and_fulfilled(self, api):
        """PRD §3.8: "at creation, the provisional variant counts orders in either
        `ACCEPTED` or `FULFILLED` status, capturing in-flight accepted sales; at
        finalize, the final variant counts only `FULFILLED` orders, so
        accepted-but-unfulfilled and rejected sales drop out, which changes gross
        sales and therefore the percentage rent and total."
        PRD §3.8: "The `total_rent_cents` is the lesser of `rent_cap_cents` and the
        sum of the base and percentage components."

        Design: Difficulty/dual_variant_calc/rent_settlement_provisional_vs_final
        """
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        place_accepted_order(ctx, 3000000, item_count=2)
        place_fulfilled_order(ctx, 4000000, item_count=3)

        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        assert se["gross_sales_cents"] == 7000000, "provisional counts ACCEPTED+FULFILLED"
        assert se["total_rent_cents"] == 360000

    def test_final_variant_counts_fulfilled_only(self, api):
        """PRD §3.8: "at creation, the provisional variant counts orders in either
        `ACCEPTED` or `FULFILLED` status, capturing in-flight accepted sales; at
        finalize, the final variant counts only `FULFILLED` orders, so
        accepted-but-unfulfilled and rejected sales drop out, which changes gross
        sales and therefore the percentage rent and total."

        Design: Difficulty/dual_variant_calc/rent_settlement_provisional_vs_final
        """
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        place_accepted_order(ctx, 3000000, item_count=2)
        place_fulfilled_order(ctx, 4000000, item_count=3)

        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        fin = validate_success(api.finalize_settlement(se["id"], HM), 200)
        assert fin["gross_sales_cents"] == 4000000, "final counts FULFILLED only"
        assert fin["total_rent_cents"] == 200000


class TestRentCombinatorialFormula:
    """combinatorial_formula / rent_total_nested_min_max."""

    def test_percentage_rent_component_above_breakpoint(self, api):
        """PRD §3.8: "The percentage component, `percentage_rent_cents`, is
        `percentage_rate` multiplied by the greater of zero and (gross sales minus
        `natural_breakpoint_cents`), rounded half up to a whole cent — percentage
        rent applies only to sales strictly above the breakpoint."

        Design: Difficulty/combinatorial_formula/rent_total_nested_min_max
        """
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        place_accepted_order(ctx, 3000000, item_count=2)
        place_fulfilled_order(ctx, 4000000, item_count=3)

        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        assert se["percentage_rent_cents"] == 160000

    def test_total_is_base_plus_percentage_under_cap(self, api):
        """PRD §3.8: "The `total_rent_cents` is the lesser of `rent_cap_cents` and
        the sum of the base and percentage components."
        PRD §3.8: "The base charged is `base_rent_cents` multiplied by active days,
        divided by period days, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/rent_total_nested_min_max
        """
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        place_accepted_order(ctx, 3000000, item_count=2)
        place_fulfilled_order(ctx, 4000000, item_count=3)

        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        assert se["base_rent_charged_cents"] == 200000
        assert se["total_rent_cents"] == 360000


class TestProratedRoundThenSum:
    """combinatorial_formula / prorated_base_round_then_sum. Lease starts mid-period
    (2026-06-11) so base prorates 20/30 days; base and percentage are each rounded
    then summed."""

    def _setup(self):
        ctx = open_stall(
            clock="2026-06-15T18:00:00Z",
            lease_overrides={"start_date": "2026-06-11"},
        )
        place_fulfilled_order(ctx, 6250003, item_count=5)
        return ctx

    def test_base_is_prorated_to_active_days(self, api):
        """PRD §3.8: "The base charged is `base_rent_cents` multiplied by active
        days, divided by period days, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/prorated_base_round_then_sum
        """
        ctx = self._setup()
        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        fin = validate_success(api.finalize_settlement(se["id"], HM), 200)
        assert fin["base_rent_charged_cents"] == 133333

    def test_total_rounds_each_component_then_sums(self, api):
        """PRD §2.7: "Rent is computed in a strict round-then-sum order: the
        prorated base component and the percentage-rent component are each rounded
        to a whole cent independently, and only then are the two already-rounded
        integers added together."

        Design: Difficulty/combinatorial_formula/prorated_base_round_then_sum
        """
        ctx = self._setup()
        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        fin = validate_success(api.finalize_settlement(se["id"], HM), 200)
        assert fin["percentage_rent_cents"] == 100000
        assert fin["total_rent_cents"] == 233333, "round-then-sum; NOT 233334"


class TestBreakpointBoundary:
    """boundary_precision_check / breakpoint_zero_at_equality. Final FULFILLED sales
    exactly equal the breakpoint, so max(0, S-K) == 0."""

    def _setup(self):
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        place_fulfilled_order(ctx, 5000000, item_count=4)
        return ctx

    def test_percentage_rent_zero_at_breakpoint_equality(self, api):
        """PRD §3.8: "The percentage component, `percentage_rent_cents`, is
        `percentage_rate` multiplied by the greater of zero and (gross sales minus
        `natural_breakpoint_cents`), rounded half up to a whole cent — percentage
        rent applies only to sales strictly above the breakpoint."

        Design: Difficulty/boundary_precision_check/breakpoint_zero_at_equality
        """
        ctx = self._setup()
        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        fin = validate_success(api.finalize_settlement(se["id"], HM), 200)
        assert fin["percentage_rent_cents"] == 0

    def test_total_equals_base_only_at_breakpoint_equality(self, api):
        """PRD §3.8: "The `total_rent_cents` is the lesser of `rent_cap_cents` and
        the sum of the base and percentage components."

        Design: Difficulty/boundary_precision_check/breakpoint_zero_at_equality
        """
        ctx = self._setup()
        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        fin = validate_success(api.finalize_settlement(se["id"], HM), 200)
        assert fin["total_rent_cents"] == 200000


class TestRentLedgerConservation:
    """compensating_invariant / rent_ledger_conservation_finalize_then_void. The
    lease ledger is debited on finalize and credited back on void."""

    def _setup(self):
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        place_fulfilled_order(ctx, 4000000, item_count=3)
        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        fin = validate_success(api_client.finalize_settlement(se["id"], HM), 200)
        return ctx, se, fin

    def test_finalize_debits_outstanding_balance(self, api):
        """PRD §2.7: "Finalizing a settlement debits this balance by the
        settlement's total rent, and voiding a finalized settlement credits it back
        by exactly the same amount, so that a finalize followed by a void leaves the
        balance where it started."

        Design: Difficulty/compensating_invariant/rent_ledger_conservation_finalize_then_void
        """
        ctx, se, fin = self._setup()
        lease = validate_success(api.get_lease(ctx["lease_id"], HM), 200)
        assert lease["outstanding_balance_cents"] == 200000

    def test_void_credits_balance_back_to_zero(self, api):
        """PRD §3.8: "voiding is permitted only while the settlement is `FINALIZED`,
        and it credits the lease ledger by subtracting the settlement's
        `total_rent_cents` from the lease's `outstanding_balance_cents` (incrementing
        the lease's `version`), exactly reversing the debit that finalize applied."

        Design: Difficulty/compensating_invariant/rent_ledger_conservation_finalize_then_void
        """
        ctx, se, fin = self._setup()
        validate_success(api.void_settlement(se["id"], HM), 200)
        lease = validate_success(api.get_lease(ctx["lease_id"], HM), 200)
        assert lease["outstanding_balance_cents"] == 0


def test_finalize_when_already_finalized_rejected(api):
    """PRD §3.8: "Finalizing a settlement moves it from `PROVISIONAL` to the terminal
    `FINALIZED` status and is permitted only while it is `PROVISIONAL`."
    PRD §2.10: "`ERR_SETTLEMENT_NOT_PROVISIONAL` when finalizing or disputing a
    settlement that is not `PROVISIONAL` or voiding a settlement that is not
    `FINALIZED`."

    Design: Corner/state_machines/settlement_finalize_when_finalized_rejected
    """
    ctx = open_stall(clock="2026-06-15T18:00:00Z")
    place_fulfilled_order(ctx, 4000000, item_count=3)
    se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
    validate_success(api.finalize_settlement(se["id"], HM), 200)

    res = api.finalize_settlement(se["id"], HM)
    validate_error(res, "ERR_SETTLEMENT_NOT_PROVISIONAL")

    lease = validate_success(api.get_lease(ctx["lease_id"], HM), 200)
    assert lease["outstanding_balance_cents"] == 200000, "no double debit"


def test_deposit_forfeiture_prorated_on_early_terminate(api):
    """PRD §3.2: "The forfeited amount is the deposit multiplied by remaining days,
    divided by term days, rounded half up to a whole cent; the refund is the deposit
    minus that forfeited amount."

    Design: Corner/calculations/deposit_forfeiture_prorated_on_early_terminate
    """
    ctx = open_stall(clock="2026-06-15T18:00:00Z")
    validate_success(api.set_clock("2026-09-01T00:00:00Z", HM), 200)

    res = api.terminate_lease(ctx["lease_id"], HM)
    body = validate_success(res, 200)
    assert body["deposit_refund_cents"] == 42991
    lease = validate_success(api.get_lease(ctx["lease_id"], HM), 200)
    assert lease["status"] == "TERMINATED"
