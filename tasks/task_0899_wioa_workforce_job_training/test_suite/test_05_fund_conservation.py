"""Dual-pool fund conservation: forward commitment paired with compensating release
restores balances with zero drift (ITA pool and supportive pool)."""
from test_helpers import (
    validate_success, ApiErrorId,
    setup_obligated_voucher, setup_approved_supportive_payment,
    assert_ita_pool_conserved, assert_supportive_pool_conserved,
    CM, FO, ANY,
)


# --- ITA pool: obligate then cancel a never-disbursed voucher ---
def test_ita_obligate_then_cancel_restores_available_with_zero_drift(api):
    """PRD §2.7: "A forward obligation that moves an amount out of available and into
    obligated, paired with a later compensating cancellation of a never-disbursed voucher
    that moves the same amount back from obligated into available, restores
    `ita_budget_available_cents` to its pre-obligation value with zero drift."

    Design: Difficulty/compensating_invariant/ita_budget_conservation_obligate_cancel
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=800000)  # total 5,000,000
    cancelled = validate_success(api.cancel_voucher(ctx["v_id"], CM))
    assert cancelled["status"] == "CANCELLED", cancelled
    area = validate_success(api.get_local_area(ctx["la_id"], ANY))
    assert area["ita_budget_available_cents"] == 5000000, area
    assert area["ita_budget_obligated_cents"] == 0, area
    assert area["ita_budget_expended_cents"] == 0, area
    assert_ita_pool_conserved(area)


def test_ita_forward_obligation_leg_holds_invariant(api):
    """PRD §2.7: "At all times after every voucher transition, the sum of
    `ita_budget_available_cents`, `ita_budget_obligated_cents`, and
    `ita_budget_expended_cents` equals `ita_budget_total_cents`."

    Design: Difficulty/compensating_invariant/ita_budget_conservation_obligate_cancel
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=800000)
    area = validate_success(api.get_local_area(ctx["la_id"], ANY))
    # Forward leg: 800000 moved from available into obligated.
    assert area["ita_budget_available_cents"] == 4200000, area
    assert area["ita_budget_obligated_cents"] == 800000, area
    assert area["ita_budget_expended_cents"] == 0, area
    assert_ita_pool_conserved(area)


# --- Supportive pool: approve then void from APPROVED ---
def test_supportive_approve_then_void_restores_available_with_zero_drift(api):
    """PRD §2.7: "A forward approval that moves an amount from available into obligated,
    paired with a compensating void from the approved state that moves the same amount back
    from obligated into available, restores `supportive_available_cents` with zero drift."

    Design: Difficulty/compensating_invariant/supportive_budget_conservation_approve_void
    """
    ctx = setup_approved_supportive_payment(api, amount_cents=50000)  # cap 200,000
    voided = validate_success(api.void_supportive(ctx["ss_id"], FO))
    assert voided["status"] == "VOIDED", voided
    p = validate_success(api.get_participant(ctx["p_id"], ANY))
    assert p["supportive_available_cents"] == 200000, p
    assert p["supportive_obligated_cents"] == 0, p
    assert p["supportive_expended_cents"] == 0, p
    assert_supportive_pool_conserved(p, 200000)


def test_supportive_forward_approval_leg_holds_invariant(api):
    """PRD §2.7: "At all times after every supportive-payment transition, the sum of
    `supportive_available_cents`, `supportive_obligated_cents`, and
    `supportive_expended_cents` equals that initialized annual cap."

    Design: Difficulty/compensating_invariant/supportive_budget_conservation_approve_void
    """
    ctx = setup_approved_supportive_payment(api, amount_cents=50000)
    p = validate_success(api.get_participant(ctx["p_id"], ANY))
    # Forward leg: 50000 moved from available into obligated.
    assert p["supportive_available_cents"] == 150000, p
    assert p["supportive_obligated_cents"] == 50000, p
    assert p["supportive_expended_cents"] == 0, p
    assert_supportive_pool_conserved(p, 200000)
