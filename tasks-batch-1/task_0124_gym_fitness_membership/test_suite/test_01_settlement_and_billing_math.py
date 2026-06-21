"""Cancellation-settlement and dues/PT pricing math.

Translates Difficulty design index instances:
  dual_variant_calc / cancellation_settlement_coolingoff_vs_midterm
  dual_variant_calc / dues_proration_provisional_daily_vs_final_fixed30
  combinatorial_formula / pt_package_price_round_once_whole_package_mode_b
  combinatorial_formula / cancellation_settlement_branch_select_mode_a
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_member, register_member, pay_invoice,
    create_plan, create_location, set_clock, run_sweep, create_pt_package,
    PLAN_PLUS, PLAN_BASIC,
    api_client, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ===========================================================================
# dual_variant_calc / cancellation_settlement_coolingoff_vs_midterm
# ===========================================================================
def test_cancel_in_cooling_off_refunds_paid_dues_to_wallet(api):
    """PRD §3.7: "In the cooling-off variant, applicable when now is on or before the
    member's cooling_off_ends_at, the member is made whole: the refund equals the sum of
    gross_amount_cents across the member's PAID dues invoices (open and voided invoices are
    excluded), and no early-termination fee is charged."
    PRD §3.7: "When that net is positive, it is added to the member's wallet_credit_cents."

    Design: Difficulty/dual_variant_calc/cancellation_settlement_coolingoff_vs_midterm
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    # Joining invoice (gross 4200 for [Jun10,Jul01)) is PAID; clock still inside cooling-off.
    resp = api.cancel_member(member["id"], STAFF)
    data = validate_success(resp, 200)
    assert data["membership_status"] == "CANCELLED"
    assert data["contract_status"] == "TERMINATED"
    assert data["wallet_credit_cents"] == 4200, (
        f"cooling-off refund should equal PAID dues 4200, got {data['wallet_credit_cents']}"
    )


def test_cancel_in_cooling_off_assesses_no_etf_invoice(api):
    """PRD §3.7: "In the cooling-off variant, applicable when now is on or before the
    member's cooling_off_ends_at, the member is made whole: the refund equals the sum of
    gross_amount_cents across the member's PAID dues invoices (open and voided invoices are
    excluded), and no early-termination fee is charged."

    Design: Difficulty/dual_variant_calc/cancellation_settlement_coolingoff_vs_midterm
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    api.cancel_member(member["id"], STAFF)
    # No early-termination fee in cooling-off: no OPEN invoice should be created.
    invoices, meta = _list_open_invoices(api, member["id"])
    assert meta["total_count"] == 0, (
        f"cooling-off cancel charges no ETF, expected zero OPEN invoices, got {meta['total_count']}"
    )


# ===========================================================================
# combinatorial_formula / cancellation_settlement_branch_select_mode_a
# ===========================================================================
def test_cancel_mid_term_bills_flat_etf_and_leaves_wallet_zero(api):
    """PRD §3.7: "In the mid-term variant, applicable when now is strictly after
    cooling_off_ends_at but on or before term_ends_at, there is no refund and the flat
    early_termination_fee_cents from the plan is assessed."
    PRD §3.7: "When that net is negative — which is the mid-term case where the fee applies —
    an OPEN dues invoice is created for the absolute value of the net (the fee is billed); the
    fee never reduces wallet_credit_cents below zero."

    Design: Difficulty/combinatorial_formula/cancellation_settlement_branch_select_mode_a
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    # Advance well past cooling_off_ends_at (2026-06-17), before term_ends_at -> IN_TERM.
    set_clock("2026-07-15T00:00:00Z")
    run_sweep()
    resp = api.cancel_member(member["id"], STAFF)
    data = validate_success(resp, 200)
    assert data["membership_status"] == "CANCELLED"
    assert data["wallet_credit_cents"] == 0, (
        f"mid-term cancel gives no refund, wallet stays 0, got {data['wallet_credit_cents']}"
    )
    invoices, meta = _list_open_invoices(api, member["id"])
    assert meta["total_count"] == 1, f"expected one OPEN ETF invoice, got {meta['total_count']}"
    assert invoices[0]["amount_due_cents"] == 15000, (
        f"flat ETF should be billed as 15000, got {invoices[0]['amount_due_cents']}"
    )


def test_cancel_mid_term_sets_contract_terminated(api):
    """PRD §3.7: "Cancellation sets membership_status to CANCELLED and, unless the contract
    was already FULFILLED, drives contract_status to the terminal TERMINATED."

    Design: Difficulty/combinatorial_formula/cancellation_settlement_branch_select_mode_a
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    set_clock("2026-07-15T00:00:00Z")
    run_sweep()
    resp = api.cancel_member(member["id"], STAFF)
    data = validate_success(resp, 200)
    assert data["membership_status"] == "CANCELLED"
    assert data["contract_status"] == "TERMINATED"


# ===========================================================================
# dual_variant_calc / dues_proration_provisional_daily_vs_final_fixed30
# ===========================================================================
def test_provisional_first_invoice_uses_daily_calendar_denominator(api):
    """PRD §3.8: "For a provisional first or partial period — the variant pinned at first
    invoice creation — the system uses the daily calendar method: it counts the covered days as
    the whole days in the half-open span from period_start up to but not including period_end,
    counts the billing days as the whole days in the full calendar month that contains
    period_start, and sets the gross to the base multiplied by covered days divided by billing
    days, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/dues_proration_provisional_daily_vs_final_fixed30
    """
    plan = create_plan(PLAN_PLUS)  # monthly_dues_cents 6000
    location = create_location()
    # First period [2026-05-10,2026-06-01): 22 covered days, May has 31 calendar days.
    member, joining = register_member(
        plan["id"], location["id"], clock="2026-05-10T00:00:00Z",
        period_start="2026-05-10T00:00:00Z", period_end="2026-06-01T00:00:00Z",
        due_date="2026-05-10T00:00:00Z",
    )
    resp = api.get_dues_invoice(joining["id"], STAFF)
    data = validate_success(resp, 200)
    # round_half_up(6000 * 22 / 31) = round_half_up(4258.06...) = 4258
    assert data["gross_amount_cents"] == 4258, (
        f"provisional daily-calendar gross should be 4258, got {data['gross_amount_cents']}"
    )
    assert data["status"] == "OPEN"


def test_provisional_invoice_amount_due_follows_gross(api):
    """PRD §3.8: "In every variant wallet_applied_cents and amount_due_cents follow the
    computed gross."
    PRD §3.8: "amount_due_cents is the gross minus the wallet applied, never below zero."

    Design: Difficulty/dual_variant_calc/dues_proration_provisional_daily_vs_final_fixed30
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    member, joining = register_member(
        plan["id"], location["id"], clock="2026-05-10T00:00:00Z",
        period_start="2026-05-10T00:00:00Z", period_end="2026-06-01T00:00:00Z",
        due_date="2026-05-10T00:00:00Z",
    )
    data = validate_success(api.get_dues_invoice(joining["id"], STAFF), 200)
    # Fresh member has zero wallet credit, so amount_due == gross.
    assert data["wallet_applied_cents"] == 0
    assert data["amount_due_cents"] == data["gross_amount_cents"] == 4258


# ===========================================================================
# combinatorial_formula / pt_package_price_round_once_whole_package_mode_b
# ===========================================================================
def test_pt_package_price_rounds_whole_package_once(api):
    """PRD §3.9: "The evaluation order is pinned: the discount is applied to the whole
    list_price_cents — the package's list price is multiplied by one minus the discount
    fraction — and the result is rounded half-up to whole cents exactly once."
    PRD §3.9: "The price is not computed per session and then summed."

    Design: Difficulty/combinatorial_formula/pt_package_price_round_once_whole_package_mode_b
    """
    plan = create_plan(PLAN_PLUS, pt_discount_pct=0.15)  # 0.15 discount
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    resp = api.create_pt_package(
        {"member_id": member["id"], "sessions_purchased": 3, "list_price_cents": 39990}, STAFF
    )
    data = validate_success(resp, 201)
    # round_half_up(39990 * 0.85) = round_half_up(33991.5) = 33992 (NOT the per-session-sum 33993)
    assert data["price_paid_cents"] == 33992, (
        f"round-once-whole price should be 33992, got {data['price_paid_cents']}"
    )
    assert data["sessions_remaining"] == 3
    assert data["status"] == "ACTIVE"


def test_pt_package_created_active_with_full_sessions(api):
    """PRD §3.6: "On creation the package's sessions_remaining equals sessions_purchased and
    its status is ACTIVE."

    Design: Difficulty/combinatorial_formula/pt_package_price_round_once_whole_package_mode_b
    """
    plan = create_plan(PLAN_PLUS, pt_discount_pct=0.15)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    data = validate_success(
        api.create_pt_package(
            {"member_id": member["id"], "sessions_purchased": 3, "list_price_cents": 39990}, STAFF
        ), 201
    )
    assert data["sessions_remaining"] == data["sessions_purchased"] == 3
    assert data["status"] == "ACTIVE"


# --- helpers ---
def _list_open_invoices(api, member_id):
    from test_helpers import validate_paginated
    resp = api.list_dues_invoices(STAFF, params={"member_id": member_id, "status": "OPEN"})
    return validate_paginated(resp)
