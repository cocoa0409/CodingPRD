"""Event-block lifecycle: confirm/reopen cycle, underfilled confirm, close dependency on
appointment terminality, cancel cascade to appointments + credit refund, deposit
computation, and reopen-in-progress guard.

Queue A (Difficulty): non_linear_state_machine/nls_event_block_confirm_reopen_cycle;
                      boundary_precision_check/bpc_block_confirm_min_appointments_boundary;
                      cross_entity_state_dependency/ces_block_close_depends_on_appointments_terminal;
                      transitive_cascade/tc_block_cancel_to_appt_to_credit_refund.
Queue B (Corner): section `state_machines` (reopen-in-progress);
                  section `calculations` (group / bridal deposit).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_chair, create_member, create_membership_plan,
    setup_confirmed_block, setup_event_block_with_two_appointments,
    pay_deposit, confirm_block, current_block_version, check_in,
    make_stylist_headers, TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]


# ─── Queue A: HOLD -> CONFIRMED -> HOLD cycle ─────────────────────────────────

def test_confirm_then_reopen_returns_block_to_hold(api):
    """PRD §3.11: "A confirmed block can be reopened for revision by a `FrontDesk`
    operator, advancing `CONFIRMED → HOLD`; this requires the block to be `CONFIRMED`
    (otherwise `ERR_EVENT_BLOCK_NOT_CONFIRMED`, 409) ... the chairs remain reserved and the
    `version` increments by one."

    Design: Difficulty/non_linear_state_machine/nls_event_block_confirm_reopen_cycle
    """
    ctx = setup_confirmed_block()
    assert ctx["block"]["status"] == "CONFIRMED"
    v = current_block_version(ctx["block"]["id"])
    res = api.reopen_event_block(
        ctx["block"]["id"], {"expected_event_block_version": v}, FD)
    reopened = validate_success(res, 200)
    assert reopened["status"] == "HOLD"


def test_reopened_block_can_be_reconfirmed(api):
    """PRD §3.11: "Confirming a held block is a `FrontDesk` action advancing
    `HOLD → CONFIRMED`; it requires the block to be in `HOLD` (otherwise
    `ERR_EVENT_BLOCK_NOT_HOLD`, 409) ... Confirmation locks the reserved chairs for the
    window and increments the block's `version` by one."

    After a HOLD -> CONFIRMED -> HOLD cycle the block is back in HOLD and can be confirmed
    again (deposit already met, two appointments still BOOKED).

    Design: Difficulty/non_linear_state_machine/nls_event_block_confirm_reopen_cycle
    """
    ctx = setup_confirmed_block()
    block_id = ctx["block"]["id"]
    v = current_block_version(block_id)
    validate_success(api.reopen_event_block(
        block_id, {"expected_event_block_version": v}, FD), 200)
    assert validate_success(api.get_event_block(block_id, FD), 200)["status"] == "HOLD"
    v2 = current_block_version(block_id)
    res = api.confirm_event_block(block_id, {"expected_event_block_version": v2}, FD)
    reconfirmed = validate_success(res, 200)
    assert reconfirmed["status"] == "CONFIRMED"


# ─── Queue A: underfilled confirm boundary (exactly 1 < 2) ────────────────────

def test_confirm_with_single_appointment_underfilled(api):
    """PRD §3.11: "requires at least two appointments referencing the block to be in
    `BOOKED` status (otherwise `ERR_BLOCK_UNDERFILLED`, 409) ..."

    A HOLD GROUP block with deposit met but only ONE BOOKED appointment cannot be confirmed.

    Design: Difficulty/boundary_precision_check/bpc_block_confirm_min_appointments_boundary
    """
    chair_a = create_chair(label="Chair A")
    from test_helpers import create_style_service, create_stylist
    service = create_style_service()
    stylist = create_stylist(full_name="S One")
    org = create_member(full_name="Org")
    block = validate_success(api.create_event_block(
        {"organizer_member_id": org["id"], "block_type": "GROUP",
         "window_start_minute": 540, "window_end_minute": 900,
         "reserved_chair_ids": [chair_a["id"]], "party_size": 2}, FD), 201)
    validate_success(api.create_appointment(
        {"member_id": org["id"], "chair_id": chair_a["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT",
         "event_block_id": block["id"], "expected_event_block_version": block["version"]},
        FD), 201)
    pay_deposit(block["id"], 4000)
    v = current_block_version(block["id"])
    res = api.confirm_event_block(block["id"], {"expected_event_block_version": v}, FD)
    validate_error(res, "ERR_BLOCK_UNDERFILLED", expected_status=409)


def test_confirm_with_two_booked_appointments_succeeds(api):
    """PRD §3.11: "requires at least two appointments referencing the block to be in
    `BOOKED` status (otherwise `ERR_BLOCK_UNDERFILLED`, 409) ..."
    PRD §3.11: "Confirmation locks the reserved chairs for the window and increments the
    block's `version` by one."

    A block with exactly TWO BOOKED appointments and deposit met confirms successfully
    (the boundary value 2 satisfies the >= 2 requirement).

    Design: Difficulty/boundary_precision_check/bpc_block_confirm_min_appointments_boundary
    """
    ctx = setup_event_block_with_two_appointments()
    pay_deposit(ctx["block"]["id"], 4000)
    v = current_block_version(ctx["block"]["id"])
    res = api.confirm_event_block(
        ctx["block"]["id"], {"expected_event_block_version": v}, FD)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED"


# ─── Queue A: close depends on all appointments terminal ──────────────────────

def test_close_rejected_while_block_has_open_appointments(api):
    """PRD §3.11: "Closing a block is a `FrontDesk` action advancing `CHECKED_IN → CLOSED`;
    it requires the block to be `CHECKED_IN` (otherwise `ERR_EVENT_BLOCK_NOT_CLOSEABLE`,
    409), requires every block appointment to be in a terminal `lifecycle_status` of
    `COMPLETED`, `NO_SHOW`, or `CANCELLED` (otherwise `ERR_BLOCK_HAS_OPEN_APPOINTMENTS`,
    409) ..."

    Block CHECKED_IN (one appointment checked in), the other still BOOKED -> close rejected.

    Design: Difficulty/cross_entity_state_dependency/ces_block_close_depends_on_appointments_terminal
    """
    ctx = setup_confirmed_block()
    block_id = ctx["block"]["id"]
    # Check in the first block appointment -> block cascades CONFIRMED -> CHECKED_IN.
    check_in(ctx["appt1"]["id"], "ON_TIME")
    block_now = validate_success(api.get_event_block(block_id, FD), 200)
    assert block_now["status"] == "CHECKED_IN"
    v = current_block_version(block_id)
    res = api.close_event_block(block_id, {"expected_event_block_version": v}, FD)
    validate_error(res, "ERR_BLOCK_HAS_OPEN_APPOINTMENTS", expected_status=409)


def test_close_succeeds_when_all_appointments_terminal(api):
    """PRD §3.11: "Closing a block is a `FrontDesk` action advancing `CHECKED_IN → CLOSED`;
    it requires the block to be `CHECKED_IN` (otherwise `ERR_EVENT_BLOCK_NOT_CLOSEABLE`,
    409), requires every block appointment to be in a terminal `lifecycle_status` of
    `COMPLETED`, `NO_SHOW`, or `CANCELLED` (otherwise `ERR_BLOCK_HAS_OPEN_APPOINTMENTS`,
    409) ... closing releases the reserved chairs and increments the `version` by one."

    Once every block appointment is terminal (one COMPLETED, one CANCELLED), the block
    closes successfully — the inverse of the open-appointments rejection.

    Design: Difficulty/cross_entity_state_dependency/ces_block_close_depends_on_appointments_terminal
    """
    ctx = setup_confirmed_block()
    block_id = ctx["block"]["id"]
    sty1 = ctx["stylist1"]["id"]
    # Drive appt1 to COMPLETED (this checks in -> block becomes CHECKED_IN).
    check_in(ctx["appt1"]["id"], "ON_TIME")
    start_res = api.start_appointment(ctx["appt1"]["id"], make_stylist_headers(sty1))
    validate_success(start_res, 200)
    validate_success(api.complete_appointment(ctx["appt1"]["id"], make_stylist_headers(sty1)), 200)
    # Cancel appt2 (still BOOKED) -> terminal CANCELLED.
    validate_success(api.cancel_appointment(ctx["appt2"]["id"], FD), 200)

    block_now = validate_success(api.get_event_block(block_id, FD), 200)
    assert block_now["status"] == "CHECKED_IN"
    v = current_block_version(block_id)
    res = api.close_event_block(block_id, {"expected_event_block_version": v}, FD)
    closed = validate_success(res, 200)
    assert closed["status"] == "CLOSED"


# ─── Queue A: cancel cascade to appointments and credit refund ────────────────

def test_block_cancel_cascades_to_appointments_and_refunds_credits(api):
    """PRD §3.11: "Cancellation cascades: every `BOOKED` or `CHECKED_IN` appointment in the
    block is itself cancelled, each running its own cancellation side effects — credit
    refund, prepay-hold release, settlement voiding, and chair release."
    PRD §3.9: "the blowout `credits_applied` are refunded back to the member's
    `blowout_credit_balance` ..."

    VIP organizer (5 credits) consumes 1 on their block booking (balance 4); cancelling the
    block cancels both appointments and refunds the organizer's credit back to 5.

    Design: Difficulty/transitive_cascade/tc_block_cancel_to_appt_to_credit_refund
    """
    plan = create_membership_plan(tier="VIP", monthly_fee_cents=9900,
                                  included_blowout_credits=5, member_discount_pct=0.25)
    ctx = setup_event_block_with_two_appointments(
        organizer_overrides={"membership_plan_id": plan["id"]})
    block_id = ctx["block"]["id"]
    org_id = ctx["organizer"]["id"]
    # Organizer's block appointment consumed 1 credit (balance now 4).
    assert ctx["appt1"]["credits_applied"] == 1
    v = current_block_version(block_id)
    res = api.cancel_event_block(block_id, {"expected_event_block_version": v}, FD)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"

    a1 = validate_success(api.get_appointment(ctx["appt1"]["id"], FD), 200)
    a2 = validate_success(api.get_appointment(ctx["appt2"]["id"], FD), 200)
    assert a1["lifecycle_status"] == "CANCELLED"
    assert a2["lifecycle_status"] == "CANCELLED"

    org_after = validate_success(api.get_member(org_id, FD), 200)
    assert org_after["blowout_credit_balance"] == 5


def test_block_cancel_forfeits_deposit_and_cascades(api):
    """PRD §3.11: "Cancellation cascades: every `BOOKED` or `CHECKED_IN` appointment in the
    block is itself cancelled ..."
    PRD §3.11: "The block's reserved chairs are released, the `deposit_paid_cents` is
    retained as forfeited rather than refunded, and the block's `version` increments by
    one."

    After a deposit is paid and the block cancelled, deposit_paid_cents is retained (not
    refunded) while both appointments cascade to CANCELLED.

    Design: Difficulty/transitive_cascade/tc_block_cancel_to_appt_to_credit_refund
    """
    ctx = setup_event_block_with_two_appointments()
    block_id = ctx["block"]["id"]
    pay_deposit(block_id, 4000)
    v = current_block_version(block_id)
    cancelled = validate_success(
        api.cancel_event_block(block_id, {"expected_event_block_version": v}, FD), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["deposit_paid_cents"] == 4000  # forfeited, not refunded

    a1 = validate_success(api.get_appointment(ctx["appt1"]["id"], FD), 200)
    a2 = validate_success(api.get_appointment(ctx["appt2"]["id"], FD), 200)
    assert a1["lifecycle_status"] == "CANCELLED"
    assert a2["lifecycle_status"] == "CANCELLED"


# ─── Queue B: deposit computation (group / bridal) ────────────────────────────

def test_group_block_deposit_per_head(api):
    """PRD §3.11: "its required `deposit_cents` is computed: a deposit of twenty dollars
    (2,000 cents) per expected head — `party_size` multiplied by 2,000 — for a `GROUP`
    block ..."

    GROUP party_size 3 -> 3 * 2000 = 6000.

    Design: Corner/calculations/calc_event_block_group_deposit
    """
    chair_a = create_chair(label="Chair A")
    org = create_member(full_name="Org")
    res = api.create_event_block(
        {"organizer_member_id": org["id"], "block_type": "GROUP",
         "window_start_minute": 540, "window_end_minute": 900,
         "reserved_chair_ids": [chair_a["id"]], "party_size": 3}, FD)
    block = validate_success(res, 201)
    assert block["deposit_cents"] == 6000


def test_bridal_block_deposit_adds_surcharge(api):
    """PRD §3.11: "and the same per-head amount plus a one-hundred-dollar (10,000-cent)
    surcharge for a `BRIDAL` block."
    PRD §3.11: "On creation the block enters `HOLD` status with `deposit_paid_cents` at 0
    ..."

    BRIDAL party_size 4 -> 4 * 2000 + 10000 = 18000.

    Design: Corner/calculations/calc_event_block_bridal_deposit
    """
    chair_a = create_chair(label="Chair A")
    chair_b = create_chair(label="Chair B")
    org = create_member(full_name="Bride")
    res = api.create_event_block(
        {"organizer_member_id": org["id"], "block_type": "BRIDAL",
         "window_start_minute": 540, "window_end_minute": 900,
         "reserved_chair_ids": [chair_a["id"], chair_b["id"]], "party_size": 4}, FD)
    block = validate_success(res, 201)
    assert block["deposit_cents"] == 18000
    assert block["status"] == "HOLD"
    assert block["deposit_paid_cents"] == 0
