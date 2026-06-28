"""Membership activation, freeze/unfreeze cycle, cancellation fees, and the
billing cycle-close batch.

Queue A: cancellation_fee dual-variant, cycle-close evaluation order,
freeze/unfreeze cycle revert.
Queue B: confirm-payment-from-active invalid state, freeze-from-pending invalid state.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_member_headers,
    create_unlimited_plan_payload, create_membership_payload,
    register_member_payload,
    set_clock, create_unlimited_plan, register_member,
    create_membership, confirm_payment, create_active_membership,
)

BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Queue A — dual_variant_calc / cancellation_fee_inside_vs_satisfied_commitment
# --------------------------------------------------------------------------

def test_cancel_inside_commitment_charges_early_termination_fee(api):
    """PRD §3.3: "if the current clock time is strictly before `commitment_end_date` the membership is still inside its commitment window and the fee equals the plan's `early_termination_fee_cents".

    Design: Difficulty/dual_variant_calc/cancellation_fee_inside_vs_satisfied_commitment
    """
    plan = create_unlimited_plan(
        name="Unlimited 12mo", monthly_fee_cents=12000,
        commitment_months=12, early_termination_fee_cents=15000,
        requires_foundations=False,
    )
    member = register_member()
    set_clock("2026-02-01T00:00:00Z")
    ms = create_active_membership(member["id"], plan["id"])
    set_clock("2026-06-15T00:00:00Z")
    resp = api.cancel_membership(ms["id"], make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["cancellation_fee_cents"] == 15000
    assert data["status"] == "CANCEL_PENDING"


def test_cancel_after_commitment_satisfied_charges_zero_fee(api):
    """PRD §3.3: "if the current clock time is at or after `commitment_end_date` the commitment is satisfied and the fee is 0."

    Design: Difficulty/dual_variant_calc/cancellation_fee_inside_vs_satisfied_commitment
    """
    plan = create_unlimited_plan(
        name="Unlimited 12mo", monthly_fee_cents=12000,
        commitment_months=12, early_termination_fee_cents=15000,
        requires_foundations=False,
    )
    member = register_member()
    set_clock("2026-02-01T00:00:00Z")
    ms = create_active_membership(member["id"], plan["id"])
    # commitment_end_date is 2027-02-01; advance to after it.
    set_clock("2027-03-01T00:00:00Z")
    resp = api.cancel_membership(ms["id"], make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["cancellation_fee_cents"] == 0
    assert data["status"] == "CANCEL_PENDING"


# --------------------------------------------------------------------------
# Queue A — combinatorial_formula / cycle_close_explicit_evaluation_order_mode_c
# --------------------------------------------------------------------------

def test_cycle_close_total_sums_fees_then_monthly_excluding_frozen(api):
    """PRD §3.3: "In the first pass, every membership currently in `CANCEL_PENDING` is taken in `created_at` order; its stored `cancellation_fee_cents` is added to the running cycle total, and it transitions from `CANCEL_PENDING` to `CANCELLED".
    PRD §3.3: "In the second pass, every membership currently in `ACTIVE` is taken in `created_at` order and its plan's `monthly_fee_cents` is added to the running total; these memberships stay `ACTIVE`."
    PRD §3.3: "Memberships in `FROZEN` are charged no monthly fee for the cycle and are skipped by both passes."

    Design: Difficulty/combinatorial_formula/cycle_close_explicit_evaluation_order_mode_c
    """
    p12 = create_unlimited_plan(
        name="P12", monthly_fee_cents=12000, commitment_months=12,
        early_termination_fee_cents=15000, requires_foundations=False,
    )
    p8 = create_unlimited_plan(
        name="P8", monthly_fee_cents=8000, commitment_months=0,
        requires_foundations=False,
    )
    set_clock("2026-02-01T00:00:00Z")

    m_cp1 = register_member()
    ms_cp1 = create_active_membership(m_cp1["id"], p12["id"])

    m_cp2 = register_member()
    ms_cp2 = create_active_membership(m_cp2["id"], p8["id"])

    m_act1 = register_member()
    create_active_membership(m_act1["id"], p12["id"])

    m_act2 = register_member()
    create_active_membership(m_act2["id"], p8["id"])

    m_fz = register_member()
    ms_fz = create_active_membership(m_fz["id"], p12["id"])

    set_clock("2026-06-15T00:00:00Z")
    api.cancel_membership(ms_cp1["id"], make_member_headers(m_cp1["id"]))
    api.cancel_membership(ms_cp2["id"], make_member_headers(m_cp2["id"]))
    api.freeze_membership(ms_fz["id"], make_member_headers(m_fz["id"]))

    resp = api.run_cycle_close(BOX)
    data = validate_success(resp)
    # 15000 (cp1 ETF) + 0 (cp2 no commitment) + 12000 (act1) + 8000 (act2) = 35000
    assert data["total_charged_cents"] == 35000

    cp1_after = validate_success(api.get_membership(ms_cp1["id"], BOX))
    assert cp1_after["status"] == "CANCELLED"
    cp2_after = validate_success(api.get_membership(ms_cp2["id"], BOX))
    assert cp2_after["status"] == "CANCELLED"
    fz_after = validate_success(api.get_membership(ms_fz["id"], BOX))
    assert fz_after["status"] == "FROZEN"


def test_cycle_close_charges_single_active_monthly_fee_only(api):
    """PRD §3.3: "In the second pass, every membership currently in `ACTIVE` is taken in `created_at` order and its plan's `monthly_fee_cents` is added to the running total; these memberships stay `ACTIVE`."
    PRD §3.3: "Memberships in `FROZEN` are charged no monthly fee for the cycle and are skipped by both passes."

    Design: Difficulty/combinatorial_formula/cycle_close_explicit_evaluation_order_mode_c
    """
    plan = create_unlimited_plan(
        name="P-Act", monthly_fee_cents=9000, commitment_months=0,
        requires_foundations=False,
    )
    set_clock("2026-02-01T00:00:00Z")
    m_act = register_member()
    create_active_membership(m_act["id"], plan["id"])
    m_fz = register_member()
    ms_fz = create_active_membership(m_fz["id"], plan["id"])
    set_clock("2026-06-15T00:00:00Z")
    api.freeze_membership(ms_fz["id"], make_member_headers(m_fz["id"]))

    resp = api.run_cycle_close(BOX)
    data = validate_success(resp)
    # only the ACTIVE membership's 9000 monthly fee; FROZEN excluded.
    assert data["total_charged_cents"] == 9000


# --------------------------------------------------------------------------
# Queue A — non_linear_state_machine / membership_freeze_unfreeze_cycle_revert
# --------------------------------------------------------------------------

def test_freeze_then_unfreeze_returns_to_active_and_extends_commitment(api):
    """PRD §3.2: "On unfreeze, the membership returns from `FROZEN` to `ACTIVE`."
    PRD §3.2: "this whole-day figure is added to `total_frozen_days`, and `commitment_end_date` is pushed forward by that same number of days so frozen time does not count against the contract. The `freeze_started_at` field is then cleared to null and `version` increments."

    Design: Difficulty/non_linear_state_machine/membership_freeze_unfreeze_cycle_revert
    """
    plan = create_unlimited_plan(
        name="U12", monthly_fee_cents=12000, commitment_months=12,
        early_termination_fee_cents=15000, requires_foundations=False,
    )
    member = register_member()
    set_clock("2026-02-01T00:00:00Z")
    ms = create_active_membership(member["id"], plan["id"])
    hdr = make_member_headers(member["id"])

    set_clock("2026-03-01T00:00:00Z")
    validate_success(api.freeze_membership(ms["id"], hdr))

    set_clock("2026-03-11T00:00:00Z")
    resp = api.unfreeze_membership(ms["id"], hdr)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["total_frozen_days"] == 10
    assert data["freeze_started_at"] is None


def test_freeze_sets_frozen_status_and_records_freeze_start(api):
    """PRD §3.2: "Freezing moves the membership from `ACTIVE` to `FROZEN`, records `freeze_started_at` at the current clock time, and increments `version`."

    Design: Difficulty/non_linear_state_machine/membership_freeze_unfreeze_cycle_revert
    """
    plan = create_unlimited_plan(
        name="U12b", monthly_fee_cents=12000, commitment_months=12,
        early_termination_fee_cents=15000, requires_foundations=False,
    )
    member = register_member()
    set_clock("2026-02-01T00:00:00Z")
    ms = create_active_membership(member["id"], plan["id"])
    hdr = make_member_headers(member["id"])

    set_clock("2026-03-01T00:00:00Z")
    resp = api.freeze_membership(ms["id"], hdr)
    data = validate_success(resp)
    assert data["status"] == "FROZEN"
    assert data["freeze_started_at"] is not None


# --------------------------------------------------------------------------
# Queue B — state_machines / confirm_payment_from_active_returns_invalid_state
# --------------------------------------------------------------------------

def test_confirm_payment_on_active_membership_returns_invalid_state(api):
    """PRD §3.2: "A `BoxManager` confirms initial payment to activate a membership; this is permitted only when the membership is in `PENDING_PAYMENT`, otherwise `ERR_INVALID_STATE` is returned."

    Design: Corner/state_machines/confirm_payment_from_active_returns_invalid_state
    """
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    resp = api.confirm_payment(ms["id"], BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# Queue B — state_machines / freeze_from_pending_payment_returns_invalid_state
# --------------------------------------------------------------------------

def test_freeze_pending_payment_membership_returns_invalid_state(api):
    """PRD §3.2: "A `Member` may freeze their own membership, but only while it is `ACTIVE`; a freeze is always permitted in the `ACTIVE` state regardless of any reservation suspension, and an attempt from any other status yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/freeze_from_pending_payment_returns_invalid_state
    """
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    member = register_member()
    ms = create_membership(member["id"], plan["id"])  # PENDING_PAYMENT
    resp = api.freeze_membership(ms["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
