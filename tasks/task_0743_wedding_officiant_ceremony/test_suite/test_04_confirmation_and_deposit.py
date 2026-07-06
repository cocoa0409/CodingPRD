"""Confirming a booking: the ordered confirm gauntlet (state gate before fiscal,
officiant availability, deposit sufficiency) and the deposit-capture side effects
(PRD Section 3.3).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
    make_couple_headers,
)


def test_confirm_on_already_confirmed_booking_returns_not_hold(api):
    """PRD §3.3: "Confirmation is checked in order: the booking must be in `HOLD`,
    and if it is not the request is rejected with `ERR_BOOKING_NOT_HOLD` — this
    state gate is evaluated before the deposit check on the same request".

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_outranks_fiscal
    """
    ctx = fx.setup_confirmed_booking(api)
    resp = api.confirm_booking(
        ctx.booking["id"], {"deposit_amount_cents": 1}, make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_HOLD.value)


def test_confirm_state_gate_fires_even_when_deposit_would_suffice(api):
    """PRD §3.3: "the booking must be in `HOLD`, and if it is not the request is
    rejected with `ERR_BOOKING_NOT_HOLD` — this state gate is evaluated before the
    deposit check on the same request".

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_outranks_fiscal
    """
    ctx = fx.setup_confirmed_booking(api)
    resp = api.confirm_booking(
        ctx.booking["id"],
        {"deposit_amount_cents": ctx.booking["deposit_due_cents"]},
        make_couple_headers(ctx.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_HOLD.value)


def test_confirm_with_suspended_officiant_returns_unavailable(api):
    """PRD §3.3: "the assigned officiant must still be `ACTIVE`, otherwise
    `ERR_OFFICIANT_UNAVAILABLE`; the booking's date hold must not yet have expired".

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_officiant_active
    """
    ctx = fx.setup_held_booking(api)
    fx.suspend_officiant(api, ctx.officiant["id"])  # booking is HOLD, so no cascade touches it
    resp = api.confirm_booking(
        ctx.booking["id"],
        {"deposit_amount_cents": ctx.booking["deposit_due_cents"]},
        make_couple_headers(ctx.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_UNAVAILABLE.value)


def test_confirm_blocked_by_suspended_officiant_leaves_booking_in_hold(api):
    """PRD §3.3: "On success the booking's `deposit_captured_cents` is set equal to
    `deposit_due_cents`, the couple's `paid_total_cents` increases by the captured
    deposit, the officiant's `escrow_balance_cents` increases by the captured
    deposit, and the booking's date hold moves from `HELD` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_officiant_active
    """
    ctx = fx.setup_held_booking(api)
    fx.suspend_officiant(api, ctx.officiant["id"])
    api.confirm_booking(
        ctx.booking["id"],
        {"deposit_amount_cents": ctx.booking["deposit_due_cents"]},
        make_couple_headers(ctx.couple["id"]),
    )
    booking = fx.get_success_data(api.get_booking(ctx.booking["id"], make_couple_headers(ctx.couple["id"])))
    assert booking["status"] == "HOLD"
    assert booking["deposit_captured_cents"] == 0


def test_confirm_insufficient_deposit_rejected(api):
    """PRD §3.3: "and finally `deposit_amount_cents` must be at least
    `deposit_due_cents`, otherwise `ERR_DEPOSIT_INSUFFICIENT`."

    Design: Corner/validations/confirm_insufficient_deposit_returns_deposit_insufficient
    """
    ctx = fx.setup_held_booking(api)
    resp = api.confirm_booking(
        ctx.booking["id"], {"deposit_amount_cents": 1}, make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)


def test_confirm_credits_paid_total_and_escrow(api):
    """PRD §3.3: "On success the booking's `deposit_captured_cents` is set equal to
    `deposit_due_cents`, the couple's `paid_total_cents` increases by the captured
    deposit, the officiant's `escrow_balance_cents` increases by the captured
    deposit, and the booking's date hold moves from `HELD` to `CONFIRMED`."

    Design: Corner/calculations/paid_total_credited_on_confirm
    """
    ctx = fx.setup_held_booking(api)
    resp = api.confirm_booking(
        ctx.booking["id"], {"deposit_amount_cents": 70800}, make_couple_headers(ctx.couple["id"])
    )
    booking = validate_success(resp, 200)
    assert booking["deposit_captured_cents"] == 70800

    couple = fx.get_success_data(api.get_couple(ctx.couple["id"], make_couple_headers(ctx.couple["id"])))
    assert couple["paid_total_cents"] == 70800

    officiant = fx.get_officiant(api, ctx.officiant["id"])
    assert officiant["escrow_balance_cents"] == 70800
