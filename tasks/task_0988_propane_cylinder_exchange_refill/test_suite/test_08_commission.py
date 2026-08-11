"""Commission settlement: tiered marginal math, GROSS/NET variants, leak penalty (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    complete_order,
    confirm_leak,
    count_session,
    create_order,
    create_priced_site,
    create_site,
    create_statement,
    finalize_statement,
    open_session,
    register_customer_cylinder,
    register_fleet_cylinders,
    report_leak,
    setup_swap_day_balanced,
    swap_completed,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
OFFICER1 = TEST_USERS["compliance_officer_headers"]


def _setup_refunded_sale_site(commission_basis: str):
    """Site (tier threshold 5000, rate 1000bps, bonus 100bps) with, on 2026-05-01:
    order1 swap-with-return completed (2705); order2 swap-without-return completed
    (6494) then refunded same day; the day's session counted BALANCED.
    Returns the site."""
    site, _policy = create_priced_site(site_overrides={
        "commission_tier_threshold_cents": 5000,
        "commission_basis": commission_basis,
    })
    register_fleet_cylinders(site_id=site["id"], count=2, fill="FULL", serial_prefix="FX")
    customer = register_customer_cylinder(fill="EMPTY")
    swap_completed(site["id"], CLERK1, returned_cylinder_id=customer["id"])
    order2 = create_order(site["id"], CLERK1)
    complete_order(order2["id"], CLERK1, payment_cash_cents=6494)
    validate_success(api_client.refund_exchange_order(order2["id"], CLERK1), 200)
    # Drawer: 20000 + 2705 + 6494 - 6494 = 22705; cage: 0 full, 1 empty (1 quarantined).
    session = open_session(site["id"], "2026-05-01", CLERK1)
    counted = count_session(session["id"], 22705, 0, 1, CLERK1)
    assert counted["status"] == "BALANCED", "Setup failed: exact count must balance"
    advance_clock("2026-05-02T00:00:00Z")
    return site


class TestGrossVsNet:
    def test_commission_base_gross_vs_net_gross_site(self, api):
        """PRD §3.7: "The commissioned base depends on the frozen variant: under `GROSS` the refunded-in-period sales remain in the commissioned set and `base_cents` equals `gross_sales_cents`; under `NET` the refunded-in-period sales are excluded and `base_cents` is `gross_sales_cents` minus `refunds_cents`, so identical raw sales yield a smaller base under `NET`."
        PRD §3.7: "The sale's commission is the below-threshold portion multiplied by `commission_rate_bps`, plus the above-threshold portion multiplied by the sum of `commission_rate_bps` and `commission_tier2_bonus_bps`, each rate divided by ten thousand, and the whole sale figure rounded half-up to whole cents before being added into `commission_cents`"

        Design: Difficulty/dual_variant_calc/commission_base_gross_vs_net
        """
        site = _setup_refunded_sale_site("GROSS")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        final = finalize_statement(st["id"])
        assert final["status"] == "FINALIZED"
        assert final["basis_used"] == "GROSS"
        assert final["gross_sales_cents"] == 9199, "2705 + 6494"
        assert final["refunds_cents"] == 6494
        assert final["base_cents"] == 9199, "refunded sale stays in the commissioned set"
        # sale 2705: 271; sale 6494 straddles the 5000 tier: below 2295, above 4199 ->
        # round_half_up(229.50 + 461.89) = 691
        assert final["commission_cents"] == 962
        assert final["net_payable_cents"] == 962

    def test_commission_base_gross_vs_net_net_site(self, api):
        """PRD §3.7: "under `NET` the refunded-in-period sales are excluded and `base_cents` is `gross_sales_cents` minus `refunds_cents`, so identical raw sales yield a smaller base under `NET`."

        Design: Difficulty/dual_variant_calc/commission_base_gross_vs_net
        """
        site = _setup_refunded_sale_site("NET")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        final = finalize_statement(st["id"])
        assert final["status"] == "FINALIZED"
        assert final["basis_used"] == "NET"
        assert final["gross_sales_cents"] == 9199
        assert final["refunds_cents"] == 6494
        assert final["base_cents"] == 2705, "9199 - 6494"
        assert final["commission_cents"] == 271, "only the 2705 sale is commissioned"
        assert final["net_payable_cents"] == 271


class TestPerSaleRounding:
    def test_commission_per_sale_rounding_then_sum(self, api):
        """PRD §2.5: "Two multiplication-stage rounding rules are easy to get wrong and are therefore stated here as system-wide doctrine: refill charges are rounded per tier **before** the tiers are summed, and commissions are rounded per sale **before** the per-sale amounts are summed."
        Two 2705 sales at 1000bps: round_half_up(270.5) + round_half_up(270.5) = 271 + 271 = 542; the forbidden sum-then-round order would yield 541.

        Design: Difficulty/combinatorial_formula/commission_per_sale_rounding_then_sum
        """
        site, _policy = create_priced_site()  # default tier threshold 100000: all tier 1
        register_fleet_cylinders(site_id=site["id"], count=2, fill="FULL", serial_prefix="FR")
        for _ in range(2):
            customer = register_customer_cylinder(fill="EMPTY")
            swap_completed(site["id"], CLERK1, returned_cylinder_id=customer["id"])
        session = open_session(site["id"], "2026-05-01", CLERK1)
        counted = count_session(session["id"], 25410, 0, 2, CLERK1)  # 20000 + 2*2705
        assert counted["status"] == "BALANCED"
        advance_clock("2026-05-02T00:00:00Z")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        final = finalize_statement(st["id"])
        assert final["gross_sales_cents"] == 5410
        assert final["commission_cents"] == 542, "per-sale round_half_up: 271 + 271"
        assert final["net_payable_cents"] == 542

    def test_commission_single_sale_rounds_half_up(self, api):
        """PRD §2.5: "Wherever a money figure is computed rather than supplied — tax, per-tier propane charges, per-sale commissions — the computed value is rounded half-up to whole cents."
        A single 2705 sale at 1000bps computes to 270.5 cents and rounds half-up to 271.

        Design: Difficulty/combinatorial_formula/commission_per_sale_rounding_then_sum
        """
        site, _order, _session = setup_swap_day_balanced()  # one 2705 sale, day BALANCED
        advance_clock("2026-05-02T00:00:00Z")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        final = finalize_statement(st["id"])
        assert final["gross_sales_cents"] == 2705
        assert final["commission_cents"] == 271, "round_half_up(270.5)"
        assert final["net_payable_cents"] == 271


class TestFinalizeGates:
    def test_commission_finalize_requires_all_dates_reconciled(self, api):
        """PRD §3.7: "every calendar date in the closed interval must have at least one reconciliation session for the site in `BALANCED` or `RESOLVED` — any unreconciled date rejects the finalize with `ERR_RECONCILIATION_UNRESOLVED`."

        Design: Difficulty/cross_entity_state_dependency/commission_finalize_requires_all_dates_reconciled
        """
        site, _policy = create_priced_site()
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        advance_clock("2026-05-02T00:00:00Z")  # period now closed
        res = api.finalize_commission_statement(st["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_RECONCILIATION_UNRESOLVED, expected_status=409)
        # No sales on 2026-05-01: exact count of the 20000 float balances.
        session = open_session(site["id"], "2026-05-01", CLERK1)
        counted = count_session(session["id"], 20000, 0, 0, CLERK1)
        assert counted["status"] == "BALANCED"
        final = finalize_statement(st["id"])
        assert final["status"] == "FINALIZED"
        assert final["commission_cents"] == 0, "empty sales set"

    def test_finalize_rejected_while_session_variance_flagged(self, api):
        """PRD §3.7: "every calendar date in the closed interval must have at least one reconciliation session for the site in `BALANCED` or `RESOLVED` — any unreconciled date rejects the finalize with `ERR_RECONCILIATION_UNRESOLVED`."
        A `VARIANCE_FLAGGED` session is neither `BALANCED` nor `RESOLVED`.

        Design: Difficulty/cross_entity_state_dependency/commission_finalize_requires_all_dates_reconciled
        """
        site, _policy = create_priced_site()
        session = open_session(site["id"], "2026-05-01", CLERK1)
        flagged = count_session(session["id"], 20600, 0, 0, CLERK1)  # +600 over
        assert flagged["status"] == "VARIANCE_FLAGGED"
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        advance_clock("2026-05-02T00:00:00Z")
        res = api.finalize_commission_statement(st["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_RECONCILIATION_UNRESOLVED, expected_status=409)

    def test_period_not_closed_finalize_rejected(self, api):
        """PRD §3.7: "the `period_end` must lie strictly before the current logical date (else `ERR_PERIOD_NOT_CLOSED`)"

        Design: Corner/validations/period_not_closed_finalize_rejected
        """
        site = create_site(name="Period Site")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        # Clock is still at the startup date 2026-05-01: period_end is not strictly before it.
        res = api.finalize_commission_statement(st["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_CLOSED, expected_status=422)

    def test_statement_period_over_62_days_rejected(self, api):
        """PRD §3.7: "A `PlatformAdmin` opens a commission statement for a site with a closed `period_start`–`period_end` interval: both bounds inclusive, `period_end` on or after `period_start`, and the span no longer than 62 days; malformed periods are rejected with `ERR_VALIDATION`."

        Design: Corner/validations/statement_period_over_62_days_rejected
        """
        site = create_site(name="Long Period Site")
        # 2026-05-01 .. 2026-08-01 spans 92 days > 62.
        res = api.create_commission_statement(
            {"site_id": site["id"], "period_start": "2026-05-01", "period_end": "2026-08-01"},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestLeakDeduction:
    def test_commission_leak_deduction_floor(self, api):
        """PRD §3.7: "`leak_count` is the number of leak reports for the site in `CONFIRMED` or `RESOLVED` status whose `confirmed_on` falls inside the period, and `leak_deduction_cents` is that count times 25,000 cents — a $250.00 penalty per confirmed leak."
        PRD §3.7: "The payable figure `net_payable_cents` is `commission_cents` minus `leak_deduction_cents`, floored at zero."

        Design: Corner/calculations/commission_leak_deduction_floor
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="LD")
        customer = register_customer_cylinder(fill="EMPTY")
        swap_completed(site["id"], CLERK1, returned_cylinder_id=customer["id"])
        leak = report_leak(site["id"], CLERK1, severity="MAJOR")
        confirm_leak(leak["id"], OFFICER1)  # post-sale: the absorbed empty is quarantined
        # Expected cash 22705; after the cascade the cage holds 0 full / 0 empty (1 quarantined).
        session = open_session(site["id"], "2026-05-01", CLERK1)
        counted = count_session(session["id"], 22705, 0, 0, CLERK1)
        assert counted["status"] == "BALANCED"
        advance_clock("2026-05-02T00:00:00Z")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        final = finalize_statement(st["id"])
        assert final["commission_cents"] == 271
        assert final["leak_count"] == 1
        assert final["leak_deduction_cents"] == 25000
        assert final["net_payable_cents"] == 0, "271 - 25000 floors at zero"
