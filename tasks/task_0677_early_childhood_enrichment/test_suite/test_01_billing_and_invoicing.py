"""Billing-cycle invoicing: tuition lines, proration variants, sibling discount.

Covers difficulty instances on the Membership/Invoice billing domain
(dual-variant full-cycle vs prorated, combinatorial sibling-discount tiers)
plus the single-child no-discount corner case.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    setup_billable_membership, set_clock, renew_membership,
    create_active_membership, create_child, create_program, create_room,
    create_instructor, create_session, enroll_child,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["studio_admin_headers"]
STAFF = TEST_USERS["front_desk_headers"]


def test_full_cycle_invoice_two_children_no_proration(api):
    """PRD §3.6: "Full-cycle billing applies when the membership was ACTIVE for
    the entire billing cycle. Each child's line is simply that program's
    tuition_cents, with no proration."
    PRD §3.6: "The subtotal_cents is the membership's monthly_base_fee_cents plus
    the sum of these rounded per-child tuition lines."
    PRD §3.6: "exactly two earns 0.10"
    PRD §3.6: "the final sibling_discount_cents is the smaller of the rounded raw
    discount and the largest single rounded child tuition line among the billed
    children — the discount may never exceed one full child's tuition line."
    PRD §3.6: "Finally total_cents is subtotal_cents minus sibling_discount_cents,
    floored at 0 so the total is never negative."

    Two 2500-cent lines + PLUS base 5000 => subtotal 10000; n=2 rate 0.10 over
    tuition-only 5000 => raw 500, cap 2500 => discount 500; total 9500.

    Design: Difficulty/dual_variant_calc/invoice_full_cycle_vs_mid_cycle_prorated_membership_domain
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=2, tuition_cents=2500, tier="PLUS")
    set_clock("2026-06-01T00:00:00Z")
    resp = api.renew_membership(ctx["membership"]["id"], STAFF)
    invoice = validate_success(resp, 201)
    assert invoice["subtotal_cents"] == 10000, f"subtotal {invoice['subtotal_cents']}"
    assert invoice["sibling_discount_cents"] == 500, f"discount {invoice['sibling_discount_cents']}"
    assert invoice["total_cents"] == 9500, f"total {invoice['total_cents']}"


def test_full_cycle_invoice_emits_open_invoice_on_renew(api):
    """PRD §3.6: "Renewal advances current_cycle_start forward by one cycle to the
    next cycle_anchor_day and emits a new OPEN invoice."
    PRD §3.6: "An invoice carries the membership_id it bills, the cycle_start it
    covers, and the computed subtotal_cents, sibling_discount_cents, and total_cents;
    its status is one of OPEN, PAID, or VOID."

    Renewing a full-cycle PLUS membership emits an OPEN invoice bound to the
    membership (companion assertion on the same full-cycle scenario).

    Design: Difficulty/dual_variant_calc/invoice_full_cycle_vs_mid_cycle_prorated_membership_domain
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=2, tuition_cents=2500, tier="PLUS")
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(ctx["membership"]["id"], STAFF), 201)
    assert invoice["status"] == "OPEN"
    assert invoice["membership_id"] == ctx["membership"]["id"]


def test_prorated_invoice_rounds_each_line_before_summing(api):
    """PRD §3.6: "Here each child's line is the program's tuition_cents multiplied
    by the number of active days and divided by the fixed cycle length of 30 days,
    then rounded half-up to whole cents."
    PRD §3.6: "a membership reactivated 20 days before its renewal yields 10 active
    days, so a line whose program tuition is 2500 cents prorates to round-half-up
    of (2500 × 10 ÷ 30), which is 833 cents."
    PRD §3.6: "In both variants the rounding is applied to each child line before
    the lines are summed — sum-of-rounded, never round-of-sum."

    Two 2500-cent lines prorated 10/30 => 833 each; sum-of-rounded 1666 (not 1667).
    subtotal 5000+1666=6666; n=2 discount round(0.10*1666)=167; total 6499.

    Design: Difficulty/combinatorial_formula/prorated_invoice_round_per_line_then_sum_mode_b
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=2, tuition_cents=2500, tier="PLUS")
    mem_id = ctx["membership"]["id"]
    family = ctx["family"]
    # Freeze then reactivate 20 days before renew so active_days = 10.
    parent_headers = fx.make_parent_headers(family["id"])
    get_success_data(api.freeze_membership(mem_id, parent_headers))
    set_clock("2026-05-22T00:00:00Z")
    get_success_data(api.activate_membership(mem_id, parent_headers))
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(mem_id, STAFF), 201)
    assert invoice["subtotal_cents"] == 6666, (
        f"sum-of-rounded subtotal expected 6666 (833+833+5000), got {invoice['subtotal_cents']}"
    )
    assert invoice["sibling_discount_cents"] == 167, f"discount {invoice['sibling_discount_cents']}"
    assert invoice["total_cents"] == 6499, f"total {invoice['total_cents']}"


def test_prorated_invoice_total_after_sibling_discount(api):
    """PRD §3.6: "The raw discount is the tuition-only amount multiplied by that
    rate. This raw discount is rounded half-up to whole cents"
    PRD §3.6: "Finally total_cents is subtotal_cents minus sibling_discount_cents,
    floored at 0 so the total is never negative."

    Companion on the prorated scenario: n=2 discount round(0.10*1666)=167 and
    total 6666-167=6499.

    Design: Difficulty/combinatorial_formula/prorated_invoice_round_per_line_then_sum_mode_b
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=2, tuition_cents=2500, tier="PLUS")
    mem_id = ctx["membership"]["id"]
    parent_headers = fx.make_parent_headers(ctx["family"]["id"])
    get_success_data(api.freeze_membership(mem_id, parent_headers))
    set_clock("2026-05-22T00:00:00Z")
    get_success_data(api.activate_membership(mem_id, parent_headers))
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(mem_id, STAFF), 201)
    assert invoice["sibling_discount_cents"] == 167
    assert invoice["total_cents"] == 6499


def test_sibling_discount_three_children_selects_fifteen_percent_tier(api):
    """PRD §3.6: "exactly three earns 0.15"
    PRD §3.6: "The raw discount is the tuition-only amount multiplied by that rate."
    PRD §3.6: "the final sibling_discount_cents is the smaller of the rounded raw
    discount and the largest single rounded child tuition line among the billed
    children — the discount may never exceed one full child's tuition line."

    Three 4000-cent lines + PLUS base 5000 => subtotal 17000; tuition-only 12000;
    n=3 rate 0.15 => raw 1800, cap 4000 => discount 1800; total 15200.

    Design: Difficulty/combinatorial_formula/sibling_discount_tiered_three_children_mode_a
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=3, tuition_cents=4000, tier="PLUS")
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(ctx["membership"]["id"], STAFF), 201)
    assert invoice["subtotal_cents"] == 17000, f"subtotal {invoice['subtotal_cents']}"
    assert invoice["sibling_discount_cents"] == 1800, f"discount {invoice['sibling_discount_cents']}"
    assert invoice["total_cents"] == 15200, f"total {invoice['total_cents']}"


def test_sibling_discount_three_children_subtotal_and_total(api):
    """PRD §3.6: "The subtotal_cents is the membership's monthly_base_fee_cents plus
    the sum of these rounded per-child tuition lines."
    PRD §3.6: "Finally total_cents is subtotal_cents minus sibling_discount_cents,
    floored at 0 so the total is never negative."
    PRD §2.9: "5000 cents for PLUS"

    Companion on the n=3 scenario: subtotal 5000 + 3*4000 = 17000 and total
    17000-1800 = 15200.

    Design: Difficulty/combinatorial_formula/sibling_discount_tiered_three_children_mode_a
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=3, tuition_cents=4000, tier="PLUS")
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(ctx["membership"]["id"], STAFF), 201)
    assert invoice["subtotal_cents"] == 17000
    assert invoice["total_cents"] == 15200


def test_single_child_membership_earns_no_sibling_discount(api):
    """PRD §3.6: "a count of one or fewer earns no discount (rate 0.00)"
    PRD §3.6: "The subtotal_cents is the membership's monthly_base_fee_cents plus
    the sum of these rounded per-child tuition lines."

    One 4000-cent line + CORE base 3000 => subtotal 7000; n=1 rate 0 => discount 0;
    total 7000.

    Design: Corner/calculations/single_child_membership_no_sibling_discount
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_billable_membership(num_children=1, tuition_cents=4000, tier="CORE")
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(ctx["membership"]["id"], STAFF), 201)
    assert invoice["subtotal_cents"] == 7000, f"subtotal {invoice['subtotal_cents']}"
    assert invoice["sibling_discount_cents"] == 0, f"discount {invoice['sibling_discount_cents']}"
    assert invoice["total_cents"] == 7000, f"total {invoice['total_cents']}"
