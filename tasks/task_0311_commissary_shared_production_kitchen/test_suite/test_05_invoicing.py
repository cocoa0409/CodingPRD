"""Monthly invoicing: subtotal rollup, loyalty discount, platform fee, pinned
evaluation order, and divergence from the wallet running balance.

Translates difficulty queue instances:
  dual_variant_calc / invoice_period_rollup_vs_wallet_running_balance
  combinatorial_formula / invoice_eval_order_discount_vs_fee_circular
"""
from test_helpers import (
    validate_success,
    make_member_operator_headers, TEST_USERS,
    register_funded_member, register_member, create_station, current_member_version,
    create_completed_booking, create_storage_unit, create_storage_assignment,
    create_invoice,
)

FM = TEST_USERS["facility_manager_headers"]


# ── Difficulty: dual_variant_calc / invoice_period_rollup_vs_wallet_running_balance ──

def test_invoice_total_diverges_from_wallet_charged(api):
    """PRD 3.13: "The total_cents is the subtotal minus the loyalty discount plus
    the platform fee." and PRD 3.13: "The platform_fee_cents is a three-percent
    facility fee computed on the subtotal before any discount". With a 2400
    booking (wallet-charged) plus a 2000 storage fee (invoice-only), the invoice
    subtotal is 4400, platform fee 132, total 4532, while lifetime_charged is
    only 2400.

    Design: Difficulty/dual_variant_calc/invoice_period_rollup_vs_wallet_running_balance
    """
    member, v = register_funded_member(amount_cents=100000, business_name="M2", plan_tier="STANDARD")
    mo = make_member_operator_headers(member["id"])
    station = create_station(name="Prep1", station_class="PREP_TABLE")
    create_storage_unit(name="Dry1", temp_class="DRY", total_slots=20,
                        temp_min_c=10.0, temp_max_c=25.0)
    # Completed off-peak 120-min booking → fee 2400 charged to wallet.
    create_completed_booking(member["id"], station["id"],
                             "2026-07-01T12:00:00.000Z", "2026-07-01T14:00:00.000Z", v)
    v2 = current_member_version(member["id"])
    # ACTIVE DRY 5-slot assignment → monthly_fee 2000 (billed via invoice, not wallet).
    create_storage_assignment(member["id"], "DRY", 5, v2)

    invoice = create_invoice(member["id"],
                             "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z")
    assert invoice["subtotal_cents"] == 4400, f"got {invoice['subtotal_cents']}"
    assert invoice["platform_fee_cents"] == 132, f"got {invoice['platform_fee_cents']}"
    assert invoice["total_cents"] == 4532, f"got {invoice['total_cents']}"

    member_now = validate_success(api.get_member(member["id"], mo), 200)
    assert member_now["lifetime_charged_cents"] == 2400, f"got {member_now['lifetime_charged_cents']}"
    assert invoice["total_cents"] != member_now["lifetime_charged_cents"]


def test_invoice_no_discount_below_mid_tier(api):
    """PRD 3.13: "if the subtotal is at least 50000 cents the discount rate is
    ten percent; otherwise if the subtotal is at least 20000 cents the rate is
    five percent; otherwise there is no discount." A 4400 subtotal is below the
    20000 MID tier, so loyalty_discount_cents is 0.

    Design: Difficulty/dual_variant_calc/invoice_period_rollup_vs_wallet_running_balance
    """
    member, v = register_funded_member(amount_cents=100000, business_name="M2b", plan_tier="STANDARD")
    station = create_station(name="Prep1b", station_class="PREP_TABLE")
    create_storage_unit(name="Dry1b", temp_class="DRY", total_slots=20,
                        temp_min_c=10.0, temp_max_c=25.0)
    create_completed_booking(member["id"], station["id"],
                             "2026-07-01T12:00:00.000Z", "2026-07-01T14:00:00.000Z", v)
    v2 = current_member_version(member["id"])
    create_storage_assignment(member["id"], "DRY", 5, v2)
    invoice = create_invoice(member["id"],
                             "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z")
    assert invoice["subtotal_cents"] == 4400
    assert invoice["loyalty_discount_cents"] == 0


# ── Difficulty: combinatorial_formula / invoice_eval_order_discount_vs_fee_circular ──

def test_invoice_eval_order_mid_tier_boundary(api):
    """PRD 3.13: "The evaluation order is fixed: first the subtotal, then the
    discount keyed on the subtotal tier, then the platform fee on the same
    subtotal, then the total." A subtotal of exactly 20000 hits the MID tier:
    discount 1000 (5%), platform fee 600 (3%), total 19600.

    Design: Difficulty/combinatorial_formula/invoice_eval_order_discount_vs_fee_circular
    """
    member = register_member(business_name="M4")
    create_storage_unit(name="Dry50", temp_class="DRY", total_slots=50,
                        temp_min_c=10.0, temp_max_c=25.0)
    create_storage_assignment(member["id"], "DRY", 50, member["version"])
    invoice = create_invoice(member["id"],
                             "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z")
    assert invoice["subtotal_cents"] == 20000, f"got {invoice['subtotal_cents']}"
    assert invoice["loyalty_discount_cents"] == 1000, f"got {invoice['loyalty_discount_cents']}"
    assert invoice["platform_fee_cents"] == 600, f"got {invoice['platform_fee_cents']}"
    assert invoice["total_cents"] == 19600, f"got {invoice['total_cents']}"


def test_invoice_platform_fee_on_subtotal_before_discount(api):
    """PRD 3.13: "The platform_fee_cents is a three-percent facility fee computed
    on the subtotal before any discount, namely the subtotal multiplied by three
    percent, rounded to whole cents with round-half-up." For a 20000 subtotal the
    platform fee is computed on 20000 (not on the post-discount figure), giving
    600.

    Design: Difficulty/combinatorial_formula/invoice_eval_order_discount_vs_fee_circular
    """
    member = register_member(business_name="M4b")
    create_storage_unit(name="Dry50b", temp_class="DRY", total_slots=50,
                        temp_min_c=10.0, temp_max_c=25.0)
    create_storage_assignment(member["id"], "DRY", 50, member["version"])
    invoice = create_invoice(member["id"],
                             "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z")
    assert invoice["platform_fee_cents"] == 600
