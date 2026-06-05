"""Invoice finalization (coupon + tax), usage period filtering, and revenue
recognition clamping.

Queue B (corner) translations for the calculations section. The
proration_credit_and_charge_divergence instance is an excluded_because stub —
owned by the dual_variant_calc difficulty instance — and is not translated here.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    record_usage_payload,
    create_subscription_payload,
    assert_invoice_total_consistent,
    setup_jurisdiction_and_clock,
    setup_active_subscription,
    setup_converted_subscription,
    create_plan,
    create_coupon,
    create_account,
    set_clock,
    list_account_invoices,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


def test_first_invoice_fixed_once_coupon_discount_then_tax(api):
    """PRD §3.6: "if the coupon's `discount_type` is `FIXED`, the discount is the smaller of the coupon's `amount_off_cents` and the subtotal." PRD §3.6: "the taxable base is the
    subtotal minus the discount." PRD §3.6: "`tax_cents` is the taxable base multiplied by the jurisdiction's `tax_rate_bps`, divided by 10000, rounded half-up to whole cents".

    Design: Corner/calculations/first_invoice_fixed_once_coupon_discount_then_tax
    """
    setup_jurisdiction_and_clock(region_code="US-CA", tax_rate_bps=875)
    plan = create_plan(tier="BASIC", monthly_fee_cents=3000, trial_days=0)
    coupon = create_coupon(
        code="FLAT500", discount_type="FIXED", amount_off_cents=500, duration="ONCE", max_redemptions=10
    )
    account = create_account(email="fix@x.com")
    get_success_data(
        api.create_subscription(
            account["id"],
            create_subscription_payload(plan["id"], coupon_id=coupon["id"]),
            _owner(account["id"]),
        )
    )
    invoices = list_account_invoices(account["id"])
    assert invoices, "ACTIVE create should produce a first invoice"
    invoice = validate_success(api.get_invoice(invoices[0]["id"], _owner(account["id"])), 200)
    assert invoice["subtotal_cents"] == 3000, f"subtotal, got {invoice['subtotal_cents']}"
    assert invoice["discount_cents"] == 500, f"discount, got {invoice['discount_cents']}"
    assert invoice["tax_cents"] == 219, f"tax, got {invoice['tax_cents']}"
    assert invoice["total_cents"] == 2719, f"total, got {invoice['total_cents']}"
    assert_invoice_total_consistent(invoice)


def test_per_jurisdiction_tax_rate_applied(api):
    """PRD §3.6: "`tax_cents` is the taxable base multiplied by the jurisdiction's `tax_rate_bps`, divided by 10000, rounded half-up to whole cents". PRD §3.6: "a `tax_jurisdiction_id` snapshot captured from the account at finalization".

    Design: Corner/calculations/per_jurisdiction_tax_ny_rate_applied
    """
    # US-NY at 400 bps; PRO 9000 trial_days 0 -> immediate first invoice.
    plan, account, sub = setup_active_subscription(
        plan_fee_cents=9000,
        plan_tier="PRO",
        email="ny@x.com",
        region_code="US-NY",
        tax_rate_bps=400,
    )
    invoices = list_account_invoices(account["id"])
    assert invoices, "ACTIVE create should produce a first invoice"
    invoice = validate_success(api.get_invoice(invoices[0]["id"], _owner(account["id"])), 200)
    assert invoice["subtotal_cents"] == 9000, f"subtotal, got {invoice['subtotal_cents']}"
    assert invoice["discount_cents"] == 0, f"discount, got {invoice['discount_cents']}"
    assert invoice["tax_cents"] == 360, f"NY tax at 400 bps, got {invoice['tax_cents']}"
    assert invoice["total_cents"] == 9360, f"total, got {invoice['total_cents']}"


def test_usage_outside_period_rejected(api):
    """PRD §3.4: "The event is accepted only if `recorded_at` falls at or after the subscription's current `period_start` and strictly before its `period_end`; an event whose time lies outside that half-open window is rejected with `ERR_USAGE_OUT_OF_PERIOD`."

    Design: Corner/calculations/usage_outside_period_excluded_from_overage
    """
    plan, account, sub = setup_converted_subscription(
        plan_fee_cents=9000, plan_tier="PRO", trial_days=14, email="oop@x.com"
    )
    res = api.record_usage(
        account["id"],
        sub["id"],
        record_usage_payload(5000, "2026-08-15T00:00:00Z"),
        _owner(account["id"]),
    )
    validate_error(res, "ERR_USAGE_OUT_OF_PERIOD")


def test_recognized_revenue_clamps_to_total_after_period_end(api):
    """PRD §3.8: "the elapsed days are the floor of the difference between the current clock and `service_period_start` in days, clamped to the range 0 through 30." PRD §3.8:
    "The `recognized_to_date_cents` is the `total_recognizable_cents` multiplied by those elapsed days, divided by 30, rounded half-up to whole cents, and then clamped to the range from 0 through `total_recognizable_cents`."

    Design: Corner/calculations/recognized_revenue_clamps_to_full_after_period
    """
    plan, account, sub = setup_converted_subscription(
        plan_fee_cents=9000, plan_tier="PRO", trial_days=14, email="clamp@x.com"
    )
    invoices = list_account_invoices(account["id"])
    assert invoices, "convert should produce a paid first invoice"
    inv_id = invoices[0]["id"]
    set_clock("2026-08-01T00:00:00Z")
    rs = validate_success(api.get_revenue_schedule(inv_id, _owner(account["id"])), 200)
    entry = rs[0] if isinstance(rs, list) else rs
    assert entry["recognized_to_date_cents"] == 9000, (
        f"recognized after period end should clamp to 9000, got {entry['recognized_to_date_cents']}"
    )
