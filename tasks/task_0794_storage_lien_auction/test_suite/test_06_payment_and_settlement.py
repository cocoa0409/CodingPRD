"""Payment: the settlement waterfall, dual-variant surplus, parallel axes,
cascades to tenant/facility, deposit conservation, and the payment guards."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, CANONICAL,
    make_platform_admin_headers,
    assert_proceeds_identity,
    set_clock, setup_sale, setup_paid_sale, setup_buyer_suspended_with_open_sale,
    CLOCK_PAST_PAYMENT_DEADLINE,
)

ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / surplus_estimated_vs_final_diverge
# ---------------------------------------------------------------------------
def test_estimated_surplus_at_close_uses_provisional_lien(api):
    """PRD §3.5: "The sale's `estimated_surplus_cents` is the surplus projected at
    close using the provisional lien, computed by the waterfall of §3.6 with the lien
    input taken as the unit's `lien_amount_provisional_cents`."

    Design: Difficulty/dual_variant_calc/surplus_estimated_vs_final_diverge
    """
    ctx = setup_sale(api)
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["estimated_surplus_cents"] == CANONICAL["estimated_surplus_cents"]  # 46000


def test_final_settlement_surplus_uses_final_lien_and_diverges(api):
    """PRD §3.6: "For the final settlement persisted at payment, the lien input to
    the waterfall is the unit's `lien_amount_final_cents`; because the final lien is
    at least the provisional lien, the final surplus is at most the estimated surplus
    shown at close."

    Design: Difficulty/dual_variant_calc/surplus_estimated_vs_final_diverge
    """
    ctx = setup_paid_sale(api)
    settlement = validate_success(api.get_settlement(ctx["settlement_id"], ADMIN))
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert settlement["surplus_cents"] == CANONICAL["final_surplus_cents"]  # 41000
    assert settlement["surplus_cents"] != sale["estimated_surplus_cents"]   # 41000 != 46000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / settlement_waterfall_ordered_buckets
# ---------------------------------------------------------------------------
def test_settlement_waterfall_bucket_amounts(api):
    """PRD §3.6: "Bucket one, `lien_recovered_cents`, is the lesser of the gross
    proceeds and the lien figure."
    PRD §3.6: "Bucket two, `facility_fee_cents`, is the lesser of two quantities: the
    gross proceeds multiplied by the facility's `facility_fee_bps`, divided by ten
    thousand and rounded half up (this percentage is the only rounded step in the
    waterfall); and whatever remains of the gross proceeds after the lien bucket."
    PRD §3.6: "Bucket three, `surplus_cents`, is the gross proceeds minus
    `lien_recovered_cents` minus `facility_fee_cents`, which is never negative by
    construction — this is the overage owed to the tenant."

    Design: Difficulty/combinatorial_formula/settlement_waterfall_ordered_buckets
    """
    ctx = setup_paid_sale(api)
    s = validate_success(api.get_settlement(ctx["settlement_id"], ADMIN))
    assert s["lien_recovered_cents"] == CANONICAL["lien_recovered_cents"]  # 94000
    assert s["facility_fee_cents"] == CANONICAL["facility_fee_cents"]      # 15000
    assert s["surplus_cents"] == CANONICAL["final_surplus_cents"]          # 41000


def test_settlement_gross_equals_sum_of_buckets(api):
    """PRD §3.6: "The settlement's `gross_proceeds_cents` equals the sale's
    `winning_amount_cents`."
    PRD §3.6: "Bucket three, `surplus_cents`, is the gross proceeds minus
    `lien_recovered_cents` minus `facility_fee_cents`, which is never negative by
    construction — this is the overage owed to the tenant."

    Design: Difficulty/combinatorial_formula/settlement_waterfall_ordered_buckets
    """
    ctx = setup_paid_sale(api)
    s = validate_success(api.get_settlement(ctx["settlement_id"], ADMIN))
    assert s["gross_proceeds_cents"] == CANONICAL["winning_amount_cents"]  # 150000
    assert_proceeds_identity(s)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / sale_parallel_payment_and_cleanout_axes
# ---------------------------------------------------------------------------
def test_pay_advances_payment_axis_leaving_cleanout_pending(api):
    """PRD §3.6: "The winning buyer pays the amount owed on its own sale, moving the
    sale's `payment_status` from `UNPAID` to `PAID`."
    PRD §3.7: "The sale's `cleanout_status` values are `PENDING`, `COMPLETED`,
    `OVERDUE`, and `VOIDED`, and this axis evolves independently of the
    `payment_status` axis, whose values are `UNPAID`, `PAID`, `REFUNDED`, and
    `FORFEITED`."

    Design: Difficulty/non_linear_state_machine/sale_parallel_payment_and_cleanout_axes
    """
    ctx = setup_paid_sale(api)
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["payment_status"] == "PAID"
    assert sale["cleanout_status"] == "PENDING"


def test_cleanout_advances_cleanout_axis_leaving_payment_paid(api):
    """PRD §3.7: "After paying, the winning buyer reports its own unit cleaned out,
    moving the sale's `cleanout_status` from `PENDING` to `COMPLETED`."
    PRD §3.7: "A completed cleanout drives the unit from `SOLD` to the terminal
    `CLEARED`."

    Design: Difficulty/non_linear_state_machine/sale_parallel_payment_and_cleanout_axes
    """
    ctx = setup_paid_sale(api)
    sale = validate_success(api.cleanout_sale(ctx["sale_id"], ctx["buyer_hdr"]))
    assert sale["payment_status"] == "PAID"
    assert sale["cleanout_status"] == "COMPLETED"
    unit = validate_success(api.get_unit(ctx["unit_id"], ADMIN))
    assert unit["status"] == "CLEARED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / pay_cascade_settlement_to_tenant_and_facility
# ---------------------------------------------------------------------------
def test_pay_finalizes_settlement_and_credits_tenant_surplus(api):
    """PRD §3.6: "Payment cascades into settlement. The platform creates and
    finalizes a `Settlement` for the sale, recording the `sale_id` and distributing
    the hammer price through a three-bucket waterfall filled strictly in order."
    PRD §3.6: "Finalizing the settlement credits both parties in the same
    transaction: the tenant's `surplus_balance_cents` increases by the settlement's
    `surplus_cents`, and the facility's `recovery_balance_cents` increases by the sum
    of `lien_recovered_cents`, `facility_fee_cents`, and the sale's
    `buyer_premium_cents`."

    Design: Difficulty/transitive_cascade/pay_cascade_settlement_to_tenant_and_facility
    """
    ctx = setup_paid_sale(api)
    settlement = validate_success(api.get_settlement(ctx["settlement_id"], ADMIN))
    assert settlement["status"] == "FINALIZED"
    assert settlement["surplus_cents"] == CANONICAL["final_surplus_cents"]  # 41000
    tenant = validate_success(api.get_tenant(ctx["ten"], ADMIN))
    assert tenant["surplus_balance_cents"] == CANONICAL["final_surplus_cents"]  # 41000


def test_pay_credits_facility_recovery_and_settles_auction(api):
    """PRD §3.6: "Finalizing the settlement credits both parties in the same
    transaction: the tenant's `surplus_balance_cents` increases by the settlement's
    `surplus_cents`, and the facility's `recovery_balance_cents` increases by the sum
    of `lien_recovered_cents`, `facility_fee_cents`, and the sale's
    `buyer_premium_cents`."
    PRD §3.6: "The paid sale's auction, which was `CLOSED`, then advances to the
    terminal `SETTLED`."

    Design: Difficulty/transitive_cascade/pay_cascade_settlement_to_tenant_and_facility
    """
    ctx = setup_paid_sale(api)
    facility = validate_success(api.get_facility(ctx["fac"], ADMIN))
    assert facility["recovery_balance_cents"] == CANONICAL["facility_recovery_cents"]  # 131500
    auction = validate_success(api.get_auction(ctx["auc"], ADMIN))
    assert auction["status"] == "SETTLED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / deposit_conservation_hold_then_release
# ---------------------------------------------------------------------------
def test_deposit_held_at_close_conserves_total(api):
    """PRD §3.5: "The platform holds the required deposit against the winner by
    reducing that buyer's `deposit_available_cents` by 20000 cents and increasing its
    `deposit_held_cents` by 20000 cents."

    Design: Difficulty/compensating_invariant/deposit_conservation_hold_then_release
    """
    ctx = setup_sale(api)  # funded 100000, at close 20000 held
    buyer = validate_success(api.get_buyer(ctx["buyer_id"], ADMIN))
    assert buyer["deposit_available_cents"] == 80000
    assert buyer["deposit_held_cents"] == 20000
    assert buyer["deposit_available_cents"] + buyer["deposit_held_cents"] == 100000


def test_deposit_released_at_pay_conserves_total(api):
    """PRD §3.6: "Paying releases the buyer's deposit hold by reducing
    `deposit_held_cents` by 20000 cents and restoring `deposit_available_cents` by
    20000 cents."

    Design: Difficulty/compensating_invariant/deposit_conservation_hold_then_release
    """
    ctx = setup_paid_sale(api)
    buyer = validate_success(api.get_buyer(ctx["buyer_id"], ADMIN))
    assert buyer["deposit_available_cents"] == 100000
    assert buyer["deposit_held_cents"] == 0
    assert buyer["deposit_available_cents"] + buyer["deposit_held_cents"] == 100000


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / pay_requires_buyer_not_suspended
# ---------------------------------------------------------------------------
def test_suspended_buyer_cannot_pay_second_sale(api):
    """PRD §3.6: "Payment is permitted only while `payment_status` is `UNPAID`, only
    while the logical clock now is at or before the `payment_deadline` (a later
    attempt is rejected with `ERR_PAYMENT_WINDOW_EXPIRED`), and only while the paying
    buyer's `status` is not `SUSPENDED` (a suspended buyer is rejected with
    `ERR_BUYER_SUSPENDED`)."

    Design: Difficulty/cross_entity_state_dependency/pay_requires_buyer_not_suspended
    """
    ctx = setup_buyer_suspended_with_open_sale(api)
    resp = api.pay_sale(ctx["sale_b_id"], ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_BUYER_SUSPENDED.value)


def test_forfeiting_a_sale_suspends_the_buyer(api):
    """PRD §3.7: "The unit returns from `SOLD` to `LIEN_MATURED`, and the buyer's
    `status` moves from `REGISTERED` to `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/pay_requires_buyer_not_suspended
    """
    ctx = setup_buyer_suspended_with_open_sale(api)
    buyer = validate_success(api.get_buyer(ctx["buyer_id"], ADMIN))
    assert buyer["status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Corner: payment/cleanout guards
# ---------------------------------------------------------------------------
def test_cleanout_before_payment_reports_sale_not_paid(api):
    """PRD §3.7: "Cleanout requires the sale's `payment_status` to be `PAID` — an
    attempt before payment is rejected with `ERR_SALE_NOT_PAID` — and the
    `cleanout_status` to be `PENDING`."

    Design: Corner/validations/cleanout_before_pay_returns_sale_not_paid
    """
    ctx = setup_sale(api)  # UNPAID
    resp = api.cleanout_sale(ctx["sale_id"], ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_PAID.value)


def test_pay_after_deadline_reports_window_expired(api):
    """PRD §3.6: "Payment is permitted only while `payment_status` is `UNPAID`, only
    while the logical clock now is at or before the `payment_deadline` (a later
    attempt is rejected with `ERR_PAYMENT_WINDOW_EXPIRED`), and only while the paying
    buyer's `status` is not `SUSPENDED` (a suspended buyer is rejected with
    `ERR_BUYER_SUSPENDED`)."

    Design: Corner/validations/pay_after_deadline_returns_window_expired
    """
    ctx = setup_sale(api)  # buyer REGISTERED, payment_deadline 2026-03-24
    set_clock(api, CLOCK_PAST_PAYMENT_DEADLINE)  # 2026-03-25
    resp = api.pay_sale(ctx["sale_id"], ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_WINDOW_EXPIRED.value)
