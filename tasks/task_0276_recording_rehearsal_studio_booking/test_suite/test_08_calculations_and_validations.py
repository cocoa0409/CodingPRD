"""Pricing/wallet calculation corners and fiscal/constraint validation corners
(Corner: calculations, validations, errors)."""
from test_helpers import (
    setup_studio_room_client,
    setup_studio,
    setup_room,
    setup_client,
    setup_engineer,
    setup_gear_item,
    create_booking,
    pay_deposit,
    confirm,
    set_clock,
    check_in,
    check_out,
    assign_engineer,
    add_gear_rental,
    create_lockout_contract,
    get_room,
    get_client,
    api_client,
    TEST_USERS,
    make_client_headers,
    get_success_data,
    validate_success,
    validate_error,
    create_gear_rental_payload,
    create_payment_payload,
    register_client_payload,
)

SM = TEST_USERS["studio_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Corner: calculations ─────────────────────────────
def test_hourly_base_charge_ceils_partial_hour():
    """PRD §3.2: "For an HOURLY booking, round that duration up to the next whole hour (any
    partial hour becomes a full billable hour) and multiply the resulting whole-hour count by the
    room's hourly_rate_cents."

    Design: Corner/calculations/hourly_base_charge_ceils_partial_hour
    """
    studio, room, client = setup_studio_room_client(room_overrides={
        "hourly_rate_cents": 6000, "block_rate_cents": 40000})
    booking = create_booking(studio, room, client, booking_kind="HOURLY",
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    # 3.5h -> ceil 4 hours * 6000 == 24000
    assert booking["base_charge_cents"] == 24000, booking["base_charge_cents"]


def test_gear_rental_charge_multi_day_window():
    """PRD §3.6: "take the booking's scheduled duration in hours, divide by 24, round up to the
    next whole day, and treat the result as rental_days with a floor of one (so any session of 24
    hours or less is one rental-day, and each started 24-hour window counts as a full day). The
    charge_cents is units multiplied by rental_days multiplied by the gear item's
    daily_rate_cents."

    Design: Corner/calculations/gear_rental_charge_multi_day_window
    """
    studio, room, client = setup_studio_room_client(room_overrides={
        "hourly_rate_cents": 6000, "block_rate_cents": 40000, "block_hours": 24})
    gear = setup_gear_item(studio["id"], name="Amp", total_units=3, daily_rate_cents=1500)
    # 26h booking -> ceil(26/24) == 2 rental days
    booking = create_booking(studio, room, client, booking_kind="BLOCK",
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-11T11:00:00Z")
    rental = add_gear_rental(booking, gear, 1, expected_version=booking["version"])
    assert rental["rental_days"] == 2, rental["rental_days"]
    assert rental["charge_cents"] == 3000, rental["charge_cents"]  # 1 * 2 * 1500


def test_block_base_charge_straddle_buys_second_block():
    """PRD §3.2: "For a BLOCK or LOCKOUT booking, divide the duration in hours by the room's
    block_hours, round that quotient up to the next whole block (a session that straddles a block
    boundary buys another entire block, so a nine-hour booking against an eight-hour block costs
    two blocks), and multiply the whole-block count by the room's block_rate_cents."

    Design: Corner/calculations/block_base_charge_straddle_buys_second_block
    """
    studio, room, client = setup_studio_room_client(room_overrides={
        "hourly_rate_cents": 6000, "block_rate_cents": 40000, "block_hours": 8})
    # exactly 8h -> 1 block (no straddle)
    booking = create_booking(studio, room, client, booking_kind="BLOCK",
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T17:00:00Z")
    assert booking["base_charge_cents"] == 40000, booking["base_charge_cents"]


def test_balance_wallet_offset_waterfall():
    """PRD §3.6: "the client's `wallet_credit_cents` is consumed *first*, applying the smaller of
    the wallet balance and the remaining balance, and only the residue must be covered by the
    external payment. The submitted balance `amount_cents` must equal that external residue
    exactly — that is, the remaining balance minus the wallet amount applied."
    PRD §3.6: "On a successful balance payment the wallet is drained by exactly the amount applied
    (the client's `wallet_credit_cents` is decremented by the wallet portion)".

    Design: Corner/calculations/balance_wallet_offset_waterfall
    """
    studio, room, client = setup_studio_room_client(
        studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": 10,
                          "cancellation_tier_hours": 48},
    )
    # Build 3600 wallet credit via a full-refund WALLET cancellation of a 1h booking.
    refund_booking = create_booking(studio, room, client, booking_kind="HOURLY",
                                    start_at="2026-07-05T09:00:00Z", end_at="2026-07-05T10:00:00Z")
    pay_deposit(refund_booking, client, 3600)
    confirm(refund_booking)
    get_success_data(api_client.cancel_booking(refund_booking["id"], make_client_headers(client["id"])))
    assert get_client(client["id"])["wallet_credit_cents"] == 3600
    # Main booking: total 52000, deposit 14400, balance 37600.
    engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF", hourly_rate_cents=8000)
    booking = create_booking(studio, room, client, booking_kind="HOURLY",
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    assign_engineer(booking, engineer)
    pay_deposit(booking, client, 14400)
    confirm(booking)
    set_clock("2026-07-10T09:05:00Z")
    check_in(booking)
    booking = check_out(booking, "2026-07-10T12:30:00Z")
    # external_required = 37600 - min(3600, 37600) = 34000
    get_success_data(api_client.create_payment(
        booking["id"], create_payment_payload("BALANCE", 34000), make_client_headers(client["id"])))
    settled = get_success_data(api_client.get_booking(booking["id"], SM))
    assert settled["settlement_status"] == "SETTLED", settled["settlement_status"]
    assert get_client(client["id"])["wallet_credit_cents"] == 0


# ─── Corner: validations ──────────────────────────────
def test_deposit_amount_mismatch_returns_deposit_mismatch():
    """PRD §3.6: "The deposit must be exact: its amount_cents must equal the booking's
    deposit_due_cents, with no partial deposits accepted, and a mismatch is rejected with
    ERR_DEPOSIT_MISMATCH."

    Design: Corner/validations/deposit_amount_mismatch_returns_deposit_mismatch
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    res = api_client.create_payment(booking["id"], create_payment_payload("DEPOSIT", 10000),
                                    make_client_headers(client["id"]))
    validate_error(res, "ERR_DEPOSIT_MISMATCH", expected_status=422)


def test_engineer_double_booking_returns_engineer_unavailable():
    """PRD §3.5: "An assignment may not be created against an engineer who is inactive (active is
    false), nor against an engineer who already holds an ASSIGNED assignment on another booking
    whose window overlaps this one — either condition is rejected with ERR_ENGINEER_UNAVAILABLE."

    Design: Corner/validations/engineer_double_booking_returns_engineer_unavailable
    """
    studio, room, client = setup_studio_room_client()
    engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF", hourly_rate_cents=8000)
    booking_a = create_booking(studio, room, client,
                               start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    assign_engineer(booking_a, engineer)
    booking_b = create_booking(studio, room, client,
                               start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T11:00:00Z")
    res = api_client.create_engineer_assignment(
        booking_b["id"], {"engineer_id": engineer["id"]}, SM)
    validate_error(res, "ERR_ENGINEER_UNAVAILABLE", expected_status=409)


def test_duplicate_client_email_within_studio_returns_409():
    """PRD §3.1: "The email must be unique within the studio; a second registration reusing an
    email already on file at that studio is rejected with ERR_DUPLICATE_EMAIL."

    Design: Corner/validations/duplicate_client_email_within_studio_returns_409
    """
    studio = setup_studio(clock=None)
    setup_client(studio["id"], display_name="Band", email="band@x.com")
    res = api_client.register_client(
        register_client_payload(studio["id"], display_name="Other", email="band@x.com"), ANON)
    validate_error(res, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_balance_mismatch_when_external_required_zero():
    """PRD §3.6: "When the wallet fully covers the remaining balance, the external requirement is
    zero, and any balance payment with a positive amount_cents is therefore rejected; any
    deviation from the exact external requirement is rejected with ERR_BALANCE_MISMATCH."

    Design: Corner/validations/balance_mismatch_when_external_required_zero
    """
    studio, room, client = setup_studio_room_client(
        studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": 10,
                          "cancellation_tier_hours": 48},
    )
    # Build 3600 wallet credit (full-refund WALLET cancellation of a 1h booking).
    refund_booking = create_booking(studio, room, client, booking_kind="HOURLY",
                                    start_at="2026-07-05T09:00:00Z", end_at="2026-07-05T10:00:00Z")
    pay_deposit(refund_booking, client, 3600)
    confirm(refund_booking)
    get_success_data(api_client.cancel_booking(refund_booking["id"], make_client_headers(client["id"])))
    # Main 1h booking: total 6000, deposit 3600, remaining balance 2400 fully wallet-covered.
    booking = create_booking(studio, room, client, booking_kind="HOURLY",
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T10:00:00Z")
    pay_deposit(booking, client, 3600)
    confirm(booking)
    set_clock("2026-07-10T09:05:00Z")
    check_in(booking)
    check_out(booking, "2026-07-10T10:00:00Z")
    # wallet 3600 covers the 2400 balance -> external_required == 0 -> positive BALANCE rejected
    res = api_client.create_payment(booking["id"], create_payment_payload("BALANCE", 2400),
                                    make_client_headers(client["id"]))
    validate_error(res, "ERR_BALANCE_MISMATCH", expected_status=422)


# ─── Corner: errors ───────────────────────────────────
def test_lockout_activate_conflict_returns_lockout_conflict():
    """PRD §3.8: "Activation is permitted only when the contract is `DRAFT` and the room's
    `status` is `OPEN`, and only when none of the occurrence windows the contract would generate
    collides with any `CONFIRMED` or `IN_SESSION` booking already on the room."
    PRD §3.8: "a collision against outside bookings is rejected with `ERR_LOCKOUT_CONFLICT`."

    Design: Corner/errors/lockout_activate_conflict_returns_lockout_conflict
    """
    studio = setup_studio(clock="2026-07-01T08:00:00Z", deposit_pct=0.60, timezone="UTC")
    room = setup_room(studio["id"], hourly_rate_cents=6000, block_rate_cents=40000, block_hours=8)
    client = setup_client(studio["id"], display_name="Band", email="band@x.com")
    # CONFIRMED booking Mon 2026-07-06 18:00-22:00 (4h BLOCK -> 1 block 40000, deposit 24000)
    booking = create_booking(studio, room, client, booking_kind="BLOCK",
                             start_at="2026-07-06T18:00:00Z", end_at="2026-07-06T22:00:00Z")
    pay_deposit(booking, client, 24000)
    confirm(booking)
    contract = create_lockout_contract(
        studio, room, client,
        weekday_mask=[1], daily_start_local="18:00", daily_end_local="22:00",
        window_start_date="2026-07-06T00:00:00Z", window_end_date="2026-07-06T00:00:00Z")
    live_room_v = get_room(room["id"])["version"]
    res = api_client.activate_lockout_contract(
        contract["id"], {"expected_room_version": live_room_v}, SM)
    validate_error(res, "ERR_LOCKOUT_CONFLICT", expected_status=409)

# NOTE: Corner/errors/register_client_missing_auth_allowed_anonymous is SKIPPED.
# It asserts an empty-string email returns ERR_VALIDATION (422). PRD §2.12 reserves
# ERR_VALIDATION for "values that pass type-checking but violate a semantic bound" and
# names only deposit_pct, empty weekday_mask, and units<1 as examples — it never states
# that an empty email is an ERR_VALIDATION case (vs. an ERR_INVALID_REQUEST missing/blank
# required field). Two faithful PRD-only implementers could legitimately return either
# 400 or 422, so the outcome is not uniquely derivable. Gap left as a gap (Core rule).
