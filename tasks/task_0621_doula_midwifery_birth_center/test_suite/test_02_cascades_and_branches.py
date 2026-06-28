"""Non-linear state machines and transitive cascades (queue A: Difficulty).

Covers the cyclic risk loop, the Booking COMPLETED-vs-TRANSFERRED fork, the depth-3
transfer cascade, and the depth-2 payment-settles-episode cascade.
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, get_success_data,
    fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _charges(api, ep_id):
    data = get_success_data(api.list_episode_charges(ep_id, ADMIN))
    if isinstance(data, dict):
        data = data.get("items") or data.get("data") or []
    return data


# ===========================================================================
# non_linear_state_machine / nlsm_prenatal_risk_loop
# ===========================================================================
def test_risk_loop_elevated_after_first_watch(api):
    """PRD §3.7: "otherwise if the worst flag is WATCH, the tier is ELEVATED"
    PRD §3.3: "This re-derivation is cyclic: a later visit may push the tier up or pull
    it back down."

    Design: Difficulty/non_linear_state_machine/nlsm_prenatal_risk_loop
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    v1 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    fixtures.complete_visit(v1["id"], risk_flag="WATCH", blood_pressure_systolic=120)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "ELEVATED", f"first WATCH -> ELEVATED, got {ep['risk_tier']}"


def test_risk_loop_stays_elevated_when_later_visit_is_none(api):
    """PRD §3.7: "It is re-derived every time a visit is completed, and it considers only
    the episode's visits in COMPLETED status"
    PRD §3.7: "The first is the worst screening flag among them, where the flags are
    ordered with NONE lowest, WATCH in the middle, and TRANSFER highest."

    Design: Difficulty/non_linear_state_machine/nlsm_prenatal_risk_loop
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    v1 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    v2 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-15T10:00:00Z")
    fixtures.complete_visit(v1["id"], risk_flag="WATCH", blood_pressure_systolic=120)
    fixtures.complete_visit(v2["id"], risk_flag="NONE", blood_pressure_systolic=118)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "ELEVATED", \
        f"worst flag among COMPLETED is still WATCH -> stays ELEVATED, got {ep['risk_tier']}"
    v2_final = validate_success(api.get_prenatal_visit(v2["id"], MIDWIFE))
    assert v2_final["status"] == "COMPLETED"


# ===========================================================================
# non_linear_state_machine / nlsm_booking_branch_transferred_vs_completed
# ===========================================================================
def test_transfer_branch_moves_booking_to_transferred(api):
    """PRD §3.8: "The episode's active room booking, if it is in HELD, CONFIRMED, or
    IN_USE, moves to TRANSFERRED."

    Design: Difficulty/non_linear_state_machine/nlsm_booking_branch_transferred_vs_completed
    """
    ctx = fixtures.setup_in_use_booking()
    ep_id = ctx["episode"]["id"]
    bk_id = ctx["booking"]["id"]

    validate_success(api.transfer_episode(ep_id, MIDWIFE))

    booking = validate_success(api.get_booking(bk_id, ADMIN))
    assert booking["status"] == "TRANSFERRED", \
        f"transfer cascade flips IN_USE booking to TRANSFERRED, got {booking['status']}"
    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "TRANSFERRED"


def test_transfer_branch_creates_transfer_fee_charge(api):
    """PRD §3.8: "it creates a new Charge of charge_kind TRANSFER_FEE in DRAFT on the
    episode, with amount_cents equal to the fixed transfer fee of 75,000 cents"

    Design: Difficulty/non_linear_state_machine/nlsm_booking_branch_transferred_vs_completed
    """
    ctx = fixtures.setup_in_use_booking()
    ep_id = ctx["episode"]["id"]

    validate_success(api.transfer_episode(ep_id, MIDWIFE))

    transfer_fees = [c for c in _charges(api, ep_id) if c.get("charge_kind") == "TRANSFER_FEE"]
    assert len(transfer_fees) == 1, f"exactly one TRANSFER_FEE charge expected, got {len(transfer_fees)}"
    assert transfer_fees[0]["amount_cents"] == 75000, \
        f"TRANSFER_FEE amount == 75000, got {transfer_fees[0]['amount_cents']}"


# ===========================================================================
# transitive_cascade / tc_transfer_booking_charge_balance_depth3
# ===========================================================================
def test_transfer_cascade_re_derives_balance_depth3(api):
    """PRD §3.8: "it creates a new Charge of charge_kind TRANSFER_FEE in DRAFT on the
    episode, with amount_cents equal to the fixed transfer fee of 75,000 cents"
    PRD §3.10: "Step one sums client responsibility across the episode's charges: it adds
    up the client_responsibility_cents of every charge whose status is DRAFT or BILLED"

    Design: Difficulty/transitive_cascade/tc_transfer_booking_charge_balance_depth3
    """
    ctx = fixtures.setup_in_use_booking(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    bk_id = ctx["booking"]["id"]

    before = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert before["balance_due_cents"] == 160000, \
        f"before transfer balance == 160000 (estimate), got {before['balance_due_cents']}"

    validate_success(api.transfer_episode(ep_id, MIDWIFE))

    booking = validate_success(api.get_booking(bk_id, ADMIN))
    assert booking["status"] == "TRANSFERRED"
    transfer_fees = [c for c in _charges(api, ep_id) if c.get("charge_kind") == "TRANSFER_FEE"]
    assert transfer_fees and transfer_fees[0]["amount_cents"] == 75000

    after = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert after["balance_due_cents"] == 235000, \
        f"160000 estimate + 75000 transfer fee == 235000, got {after['balance_due_cents']}"


def test_transfer_cascade_terminal_booking_and_episode_states(api):
    """PRD §3.8: "When a Midwife transfers an episode (permitted from PLANNING or ACTIVE),
    the episode's clinical_status moves to TRANSFERRED"
    PRD §3.8: "The episode's active room booking, if it is in HELD, CONFIRMED, or IN_USE,
    moves to TRANSFERRED."

    Design: Difficulty/transitive_cascade/tc_transfer_booking_charge_balance_depth3
    """
    ctx = fixtures.setup_in_use_booking(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    bk_id = ctx["booking"]["id"]

    validate_success(api.transfer_episode(ep_id, MIDWIFE))

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "TRANSFERRED"
    booking = validate_success(api.get_booking(bk_id, ADMIN))
    assert booking["status"] == "TRANSFERRED"


# ===========================================================================
# transitive_cascade / tc_payment_settles_episode_charges_depth2
# ===========================================================================
def test_final_payment_settles_episode_and_pays_charges(api):
    """PRD §3.10: "When a payment drives remaining_cents to exactly 0, the plan moves
    from OPEN to PAID_OFF, and that completion cascades on the financial axis: the
    episode's financial_status moves from PLAN_ACTIVE to SETTLED, and that settlement
    marks every BILLED charge on the episode as PAID."

    Design: Difficulty/transitive_cascade/tc_payment_settles_episode_charges_depth2
    """
    ctx = fixtures.setup_billed_plan_episode(installment_count=1, global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    plan_id = ctx["plan"]["id"]
    global_charge_id = ctx["global_charge"]["id"]

    after = validate_success(api.apply_payment(plan_id, f.payment_payload(160000), BILLING))
    assert after["status"] == "PAID_OFF", f"plan -> PAID_OFF, got {after['status']}"

    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["financial_status"] == "SETTLED", f"episode -> SETTLED, got {ep['financial_status']}"

    charge = validate_success(api.get_charge(global_charge_id, BILLING))
    assert charge["status"] == "PAID", f"BILLED global-fee charge -> PAID, got {charge['status']}"


def test_payment_plan_reaches_paid_off_state(api):
    """PRD §3.10: "When a payment drives remaining_cents to exactly 0, the plan moves
    from OPEN to PAID_OFF"

    Design: Difficulty/transitive_cascade/tc_payment_settles_episode_charges_depth2
    """
    ctx = fixtures.setup_billed_plan_episode(installment_count=1, global_fee_cents=800000)
    plan_id = ctx["plan"]["id"]

    after = validate_success(api.apply_payment(plan_id, f.payment_payload(160000), BILLING))
    assert after["status"] == "PAID_OFF"
    assert after["remaining_cents"] == 0
