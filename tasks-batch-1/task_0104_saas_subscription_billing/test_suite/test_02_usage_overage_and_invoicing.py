"""Tiered usage overage, pinned discount-before-tax evaluation order, and the
included-units overage boundary.

Queue A (difficulty) translations for:
  combinatorial_formula (both instances),
  boundary_precision/overage_at_included_boundary_zero_vs_one_unit.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    add_addon_payload,
    find_line_by_kind,
    assert_invoice_total_consistent,
    TIERED_OVERAGE_TIERS,
    setup_converted_subscription,
    setup_converted_with_usage_then_renew,
    create_addon,
    create_coupon,
    record_usage,
    set_clock,
    run_renewals,
    find_renewal_invoice,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


def _renewal_lines(api, account_id, invoice_id):
    return validate_success(api.list_invoice_lines(invoice_id, _owner(account_id)))


class TestTieredOverageBands:
    """5001 recorded units select across three marginal bands."""

    def test_overage_line_walks_three_marginal_bands(self, api):
        """PRD §3.6: "The overage units are then priced by walking `overage_tiers` in order as marginal bands. Starting from a previous cap of zero and the full overage-unit count as the remaining quantity, each band charges its `rate_cents_per_unit` on the units that fall inside it: the band's width is its `up_to_units` minus the previous cap, except the final band (whose `up_to_units` is null) absorbs all that remains; the quantity taken in the band is the smaller of the remaining quantity and the band width; the band's contribution is that taken quantity multiplied by the band's `rate_cents_per_unit`."

        Design: Difficulty/combinatorial_formula/usage_overage_tiered_marginal_bands_mode_a
        """
        plan, account, sub, renewal = setup_converted_with_usage_then_renew(
            plan_fee_cents=9000,
            overage_tiers=TIERED_OVERAGE_TIERS,
            included_usage_units=1000,
            units=5001,
            usage_recorded_at="2026-06-15T00:00:00Z",
            email="use@x.com",
        )
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None, "expected a renewal invoice at 2026-07-01"
        lines = _renewal_lines(api, account["id"], inv["id"])
        overage = find_line_by_kind(lines, "OVERAGE")
        assert overage is not None, "expected an OVERAGE line"
        assert overage["amount_cents"] == 8001, (
            f"4000@2 + 1@1 = 8001, got {overage['amount_cents']}"
        )

    def test_tiered_overage_is_a_single_exact_line(self, api):
        """PRD §3.6: "Because integer rates multiply integer unit counts, the resulting `OVERAGE` line amount is exact and needs no rounding." PRD §3.6: "Each billable fact is an **invoice line** carrying its `invoice_id`, a `kind` from `SUBSCRIPTION`, `ADDON`, `OVERAGE`, `PRORATION_CREDIT`, or `PRORATION_CHARGE`".

        Design: Difficulty/combinatorial_formula/usage_overage_tiered_marginal_bands_mode_a
        """
        plan, account, sub, renewal = setup_converted_with_usage_then_renew(
            plan_fee_cents=9000,
            overage_tiers=TIERED_OVERAGE_TIERS,
            included_usage_units=1000,
            units=5001,
            usage_recorded_at="2026-06-15T00:00:00Z",
            email="use2@x.com",
        )
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None
        lines = _renewal_lines(api, account["id"], inv["id"])
        overage_lines = [ln for ln in lines if ln["kind"] == "OVERAGE"]
        assert len(overage_lines) == 1, f"expected exactly one OVERAGE line, got {len(overage_lines)}"
        assert overage_lines[0]["amount_cents"] == 8001, (
            f"exact tiered overage, got {overage_lines[0]['amount_cents']}"
        )


class TestDiscountBeforeTaxOrder:
    """Pinned evaluation: subtotal -> discount -> taxable -> tax -> total."""

    def test_renewal_invoice_pinned_discount_then_tax(self, api):
        """PRD §3.6: "First, `subtotal_cents` is the signed sum of every line's `amount_cents`".
        PRD §3.6: "if the coupon's `discount_type` is `PERCENT`, the discount is the subtotal multiplied by the coupon's `percent_off`, divided by 100, rounded half-up to whole cents". PRD §3.6: "the taxable base is the subtotal minus the discount." PRD §3.6:
        "`tax_cents` is the taxable base multiplied by the jurisdiction's `tax_rate_bps`, divided by 10000, rounded half-up to whole cents — a single rounding applied to the discounted base". PRD §3.6: "`total_cents` is the taxable base plus the tax."

        Design: Difficulty/combinatorial_formula/invoice_finalize_discount_before_tax_eval_order_mode_c
        """
        # Build PRO + SEATS + PCT10 RECURRING coupon, convert, attach add-on, meter, renew.
        seats = create_addon(code="SEATS", monthly_fee_cents=2000)
        coupon = create_coupon(
            code="PCT10", discount_type="PERCENT", percent_off=10, duration="RECURRING", max_redemptions=5
        )
        # setup_converted_with_usage_then_renew creates its own jurisdiction+plan+account.
        plan, account, sub, renewal = setup_converted_with_usage_then_renew(
            plan_fee_cents=9000,
            overage_tiers=TIERED_OVERAGE_TIERS,
            included_usage_units=1000,
            units=5001,
            usage_recorded_at="2026-06-20T00:00:00Z",
            coupon_id=coupon["id"],
            addon_id_to_attach=seats["id"],
            email="ord@x.com",
        )
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None, "expected a renewal invoice at 2026-07-01"
        invoice = validate_success(api.get_invoice(inv["id"], _owner(account["id"])), 200)
        assert invoice["subtotal_cents"] == 19001, f"subtotal, got {invoice['subtotal_cents']}"
        assert invoice["discount_cents"] == 1900, f"discount, got {invoice['discount_cents']}"
        assert invoice["tax_cents"] == 1496, f"tax, got {invoice['tax_cents']}"
        assert invoice["total_cents"] == 18597, f"total, got {invoice['total_cents']}"

    def test_renewal_invoice_total_identity_holds(self, api):
        """PRD §3.6: "`total_cents` is the taxable base plus the tax." PRD §3.6: "the taxable
        base is the subtotal minus the discount."

        Design: Difficulty/combinatorial_formula/invoice_finalize_discount_before_tax_eval_order_mode_c
        """
        seats = create_addon(code="SEATS", monthly_fee_cents=2000)
        coupon = create_coupon(
            code="PCT10", discount_type="PERCENT", percent_off=10, duration="RECURRING", max_redemptions=5
        )
        plan, account, sub, renewal = setup_converted_with_usage_then_renew(
            plan_fee_cents=9000,
            overage_tiers=TIERED_OVERAGE_TIERS,
            included_usage_units=1000,
            units=5001,
            usage_recorded_at="2026-06-20T00:00:00Z",
            coupon_id=coupon["id"],
            addon_id_to_attach=seats["id"],
            email="ord2@x.com",
        )
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None
        invoice = validate_success(api.get_invoice(inv["id"], _owner(account["id"])), 200)
        assert_invoice_total_consistent(invoice)


class TestOverageIncludedBoundary:
    """The >= vs > edge at included_usage_units."""

    def test_one_unit_over_included_yields_two_cents(self, api):
        """PRD §3.6: "From that total it subtracts the effective plan's `included_usage_units`; if the difference is negative there is no overage, so the overage-unit count is the larger of zero and that difference." PRD §3.6: "Because integer rates multiply integer unit counts, the resulting `OVERAGE` line amount is exact and needs no rounding."

        Design: Difficulty/boundary_precision_check/overage_at_included_boundary_zero_vs_one_unit
        """
        plan, account, sub, renewal = setup_converted_with_usage_then_renew(
            plan_fee_cents=9000,
            overage_tiers=TIERED_OVERAGE_TIERS,
            included_usage_units=1000,
            units=1001,
            usage_recorded_at="2026-06-10T00:00:00Z",
            email="bnd@x.com",
        )
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None, "expected a renewal invoice at 2026-07-01"
        lines = _renewal_lines(api, account["id"], inv["id"])
        overage = find_line_by_kind(lines, "OVERAGE")
        assert overage is not None, "1 unit over included must produce an OVERAGE line"
        assert overage["amount_cents"] == 2, (
            f"1 overage unit at 2 cents/unit, got {overage['amount_cents']}"
        )

    def test_usage_exactly_at_included_yields_no_overage(self, api):
        """PRD §3.6: "From that total it subtracts the effective plan's `included_usage_units`; if the difference is negative there is no overage, so the overage-unit count is the larger of zero and that difference."

        Design: Difficulty/boundary_precision_check/overage_at_included_boundary_zero_vs_one_unit
        """
        plan, account, sub, renewal = setup_converted_with_usage_then_renew(
            plan_fee_cents=9000,
            overage_tiers=TIERED_OVERAGE_TIERS,
            included_usage_units=1000,
            units=1000,
            usage_recorded_at="2026-06-10T00:00:00Z",
            email="bnd0@x.com",
        )
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None, "expected a renewal invoice at 2026-07-01"
        lines = _renewal_lines(api, account["id"], inv["id"])
        overage = find_line_by_kind(lines, "OVERAGE")
        # total_units == included -> overage_units == 0 -> no positive OVERAGE charge.
        assert overage is None or overage["amount_cents"] == 0, (
            f"usage at the included boundary must yield zero overage, got {overage}"
        )
