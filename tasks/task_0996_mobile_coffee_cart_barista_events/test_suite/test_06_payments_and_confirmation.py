"""Payments: deposit settlement cascade into booking / assignment / reservation
state, idempotent payment creation, the reopen guard, and settlement RBAC.

Queue A (Difficulty): transitive_cascade.
Queue B (Corner): state_machines, validations, rbac.
"""
from test_helpers import (
    api_client,
    fixtures as fx,
    validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    assert_payment,
    ApiErrorId,
)

ERR = ApiErrorId


def _setup_pending_deposit_with_reservation():
    """Booking PENDING_DEPOSIT (deposit_due 18600) with one ACCEPTED assignment and
    one RESERVED reservation of 5 units; deposit payment created but not settled."""
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    item = fx.create_inventory_item(on_hand_units=100)
    booking = fx.create_quote_booking(ctx)
    assignment = fx.offer_primary_assignment(ctx, booking["id"])
    assignment = get_success_data(
        api_client.accept_assignment(assignment["id"], ctx["barista_headers"]))
    reservation = fx.create_reservation(ctx, booking["id"], item["id"], 5)
    booking = fx.submit_quote(ctx, booking["id"])
    payment = get_success_data(api_client.create_payment(
        booking["id"], {"kind": "DEPOSIT", "amount_cents": 18600,
                        "idempotency_key": "dep-1"}, ctx["client_headers"]))
    ctx.update({"item": item, "booking": booking, "assignment": assignment,
                "reservation": reservation, "payment": payment})
    return ctx


# ─── transitive_cascade / payment_success_cascade_booking_assignment_inventory ───

def test_deposit_settlement_cascades_booking_to_confirmed(api):
    """PRD §3.6: "When a succeeded deposit pushes the booking's `deposit_paid_cents`
    to at least its `deposit_due_cents`, the booking automatically moves from
    `PENDING_DEPOSIT` to `CONFIRMED`: every assignment in `OFFERED` or `ACCEPTED`
    moves to `CONFIRMED`, every reservation in `RESERVED` moves to `COMMITTED` —
    still counted in the item's `reserved_units`, but no longer releasable through
    the amendment flow — the cart's derived `committed_event_count` reflects one
    more committed event, and each newly confirmed barista's
    `committed_hours_this_week` reflects the commitment."

    Settling the 18600 deposit (which exactly meets deposit_due_cents) flips the
    booking to CONFIRMED.

    Design: Difficulty/transitive_cascade/payment_success_cascade_booking_assignment_inventory
    """
    ctx = _setup_pending_deposit_with_reservation()
    settled = validate_success(
        api_client.mark_payment_succeeded(ctx["payment"]["id"], fx.OPS), 200)
    assert_payment(settled)
    assert settled["status"] == "SUCCEEDED", settled

    booking = validate_success(api_client.get_booking(ctx["booking"]["id"], fx.OPS), 200)
    assert booking["status"] == "CONFIRMED", booking
    assert booking["deposit_paid_cents"] == 18600, booking


def test_deposit_settlement_cascades_to_assignment_and_reservation(api):
    """PRD §3.6: "When a succeeded deposit pushes the booking's `deposit_paid_cents`
    to at least its `deposit_due_cents`, the booking automatically moves from
    `PENDING_DEPOSIT` to `CONFIRMED`: every assignment in `OFFERED` or `ACCEPTED`
    moves to `CONFIRMED`, every reservation in `RESERVED` moves to `COMMITTED` —
    still counted in the item's `reserved_units`, but no longer releasable through
    the amendment flow — the cart's derived `committed_event_count` reflects one
    more committed event, and each newly confirmed barista's
    `committed_hours_this_week` reflects the commitment."

    The booking transition itself cascades one link deeper: the ACCEPTED
    assignment lands in CONFIRMED and the RESERVED reservation lands in COMMITTED
    while the item's reserved_units stays at 5.

    Design: Difficulty/transitive_cascade/payment_success_cascade_booking_assignment_inventory
    """
    ctx = _setup_pending_deposit_with_reservation()
    validate_success(api_client.mark_payment_succeeded(ctx["payment"]["id"], fx.OPS), 200)

    assignment = validate_success(
        api_client.get_assignment(ctx["assignment"]["id"], fx.OPS), 200)
    assert assignment["status"] == "CONFIRMED", assignment

    reservation = validate_success(
        api_client.get_reservation(ctx["reservation"]["id"], fx.OPS), 200)
    assert reservation["status"] == "COMMITTED", reservation

    item = validate_success(api_client.get_inventory_item(ctx["item"]["id"], fx.OPS), 200)
    assert item["reserved_units"] == 5, item


# ─── Corner/state_machines: payment idempotency ───────────────────────────

def test_repeated_payment_creation_with_succeeded_key_returns_same_row(api):
    """PRD §3.6: "Idempotency is key-scoped: repeating a creation with an
    `idempotency_key` whose payment already `SUCCEEDED` returns that existing
    Payment row with no duplicate state change, a key whose payment `FAILED` may
    be retried, and a key reused with a different payload is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

    Re-posting the same DEPOSIT payload under an already-succeeded idempotency key
    returns the original Payment row and does not double-count the deposit.

    Design: Corner/state_machines/payment_idempotency_same_key_returns_same_row
    """
    ctx = fx.setup_submitted_booking(package_kind="FLAT")
    first = get_success_data(api_client.create_payment(
        ctx["booking"]["id"],
        {"kind": "DEPOSIT", "amount_cents": 18600, "idempotency_key": "dep-1"},
        ctx["client_headers"]))
    validate_success(api_client.mark_payment_succeeded(first["id"], fx.OPS), 200)

    replay = get_success_data(api_client.create_payment(
        ctx["booking"]["id"],
        {"kind": "DEPOSIT", "amount_cents": 18600, "idempotency_key": "dep-1"},
        ctx["client_headers"]))
    assert replay["id"] == first["id"], (replay, first)

    booking = validate_success(api_client.get_booking(ctx["booking"]["id"], fx.OPS), 200)
    assert booking["deposit_paid_cents"] == 18600, booking


# ─── Corner/validations: reopen guard once money has landed ───────────────

def test_reopen_after_deposit_settled_rejected(api):
    """PRD §3.5: "A booking in `PENDING_DEPOSIT` returns to `QUOTE` only if no payment
    of kind `DEPOSIT` has ever succeeded for it — once a deposit has landed, the
    money must move through the refund path instead, and a reopen attempt is
    rejected with `ERR_DEPOSIT_ALREADY_PAID` (HTTP 409)."
    PRD §2.10: "State-level checks come fifth: whether the target entity's status
    permits the requested transition (`ERR_INVALID_STATE`, HTTP 409) and whether
    referenced catalog entities are `ACTIVE` (the per-entity codes of §2.9)."

    Reopening a booking whose deposit has already succeeded (leaving it CONFIRMED)
    is rejected — either by the state guard (reopen is defined only from
    PENDING_DEPOSIT) or by the deposit-paid guard; both are PRD-sanctioned
    rejections for this attempt.

    Design: Corner/validations/reopen_after_deposit_paid_rejected
    """
    ctx = fx.setup_confirmed_booking(package_kind="FLAT")
    res = api_client.reopen_booking(ctx["booking"]["id"], ctx["client_headers"])
    validate_error_is_one_of(
        res, [ERR.ERR_INVALID_STATE.value, ERR.ERR_DEPOSIT_ALREADY_PAID.value])


# ─── Corner/rbac: settlement is an operator action ────────────────────────

def test_barista_cannot_mark_payment_succeeded(api):
    """PRD §2.1: "Access to individual operations is further restricted by role; an
    attempt to perform an action outside the caller's designated role is rejected
    with an `ERR_UNAUTHORIZED` error (HTTP 403)."
    PRD §4: POST /coffee-cart/payments/{paymentId}/mark-succeeded — "Mark a
    `PENDING` payment `SUCCEEDED`; cascades booking state if the deposit threshold
    or refund is reached" — is authorized for OperationsManager only.

    A Barista attempting settlement is denied.

    Design: Corner/rbac/barista_cannot_mark_payment_succeeded
    """
    ctx = _setup_pending_deposit_with_reservation()
    res = api_client.mark_payment_succeeded(ctx["payment"]["id"],
                                            ctx["barista_headers"])
    validate_error(res, ERR.ERR_UNAUTHORIZED, expected_status=403)
