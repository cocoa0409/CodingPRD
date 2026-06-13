"""RBAC, optimistic concurrency, derived-field reconciliation, and immediate-consistency
corners (Corner: rbac, cross_cutting_complexity_layers, consistency_model)."""
from test_helpers import (
    setup_studio,
    setup_room,
    setup_client,
    setup_engineer,
    setup_gear_item,
    setup_studio_room_client,
    create_booking,
    pay_deposit,
    confirm,
    add_gear_rental,
    create_lockout_contract,
    get_room,
    api_client,
    TEST_USERS,
    make_client_headers,
    make_engineer_headers,
    get_success_data,
    validate_success,
    validate_error,
    create_gear_rental_payload,
)

SM = TEST_USERS["studio_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Corner: rbac ─────────────────────────────────────
def test_client_cannot_confirm_booking_returns_forbidden():
    """PRD §2.1: "A request that is well-formed but whose role is not permitted to perform the
    requested operation is rejected with ERR_FORBIDDEN."
    PRD §3.2: "Confirmation is a `StudioManager` action that advances `schedule_status` from
    `HELD` to `CONFIRMED`."

    Design: Corner/rbac/client_cannot_confirm_booking_returns_forbidden
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    res = api_client.confirm_booking(booking["id"], make_client_headers(client["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_engineer_cannot_create_room_returns_forbidden():
    """PRD §2.1: "A StudioManager operates the facility. This role is the operational superset for
    inventory and schedule control: it bootstraps studios, creates rooms, engineers, and gear".
    PRD §2.1: "A request that is well-formed but whose role is not permitted to perform the
    requested operation is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/engineer_cannot_create_room_returns_forbidden
    """
    studio = setup_studio(clock=None)
    engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF", hourly_rate_cents=8000)
    res = api_client.create_room(
        {"studio_id": studio["id"], "name": "Room B", "hourly_rate_cents": 6000,
         "block_rate_cents": 40000},
        make_engineer_headers(engineer["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_headers_returns_unauthenticated():
    """PRD §2.1: "Every request, except the two open bootstrap operations described below, must be
    authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting
    principal, and `X-User-Role`, which declares the capacity in which they are acting."
    PRD §2.1: "A request that omits either header, or carries a malformed value, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    studio = setup_studio(clock=None)
    res = api_client.list_clients(headers={}, params={"studio_id": studio["id"]})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Corner: cross_cutting_complexity_layers ──────────
def test_occ_stale_booking_version_on_gear_add_returns_412():
    """PRD §2.10: "If that value does not equal the booking's current version — because another
    writer has since added a gear line, recorded a payment, or otherwise cascaded a mutation onto
    the booking and thereby recomputed its derived totals — the request is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_booking_version_on_gear_add_returns_412
    """
    studio, room, client = setup_studio_room_client()
    gear = setup_gear_item(studio["id"], name="Amp", total_units=5, daily_rate_cents=1500)
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    stale_v = booking["version"]
    # first add bumps Booking.version
    add_gear_rental(booking, gear, 1, expected_version=stale_v)
    # second add still presents the pre-first-add (stale) version
    res = api_client.create_gear_rental(
        booking["id"], create_gear_rental_payload(gear["id"], 1, stale_v), SM)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_occ_correct_room_version_on_lockout_activate_succeeds():
    """PRD §2.10: "When a lockout contract is activated, the request must carry
    expected_room_version, a non-optional field carrying the client's last observed version of
    the room the contract targets."
    PRD §3.8: "On success the room's status becomes LOCKED; the system materializes one anchor
    booking (with is_series_anchor true and booking_kind LOCKOUT) plus one occurrence booking for
    each masked weekday falling inside the window".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_room_version_on_lockout_activate_succeeds
    """
    studio, room, client = setup_studio_room_client(room_overrides={
        "hourly_rate_cents": 6000, "block_rate_cents": 40000, "block_hours": 8})
    room_v = room["version"]
    contract = create_lockout_contract(
        studio, room, client,
        weekday_mask=[1], daily_start_local="18:00", daily_end_local="22:00",
        window_start_date="2026-07-06T00:00:00Z", window_end_date="2026-07-06T00:00:00Z")
    res = api_client.activate_lockout_contract(
        contract["id"], {"expected_room_version": room_v}, SM)
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE", activated["status"]
    assert activated["occurrences_generated"] == 1, activated["occurrences_generated"]
    assert get_room(room["id"])["status"] == "LOCKED"


def test_derived_amount_paid_reconciles_after_deposit():
    """PRD §3.6: "Posting a payment recomputes the booking's `amount_paid_cents`, the sum of all
    non-reversed inbound (`DEPOSIT` and `BALANCE`) payments, and increments the booking's
    `version`."
    PRD §3.6: "A deposit is paid by the `Client` and moves `settlement_status` from
    `AWAITING_DEPOSIT` to `DEPOSIT_PAID`."

    Design: Corner/cross_cutting_complexity_layers/derived_amount_paid_reconciles_after_deposit
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    get_success_data(api_client.create_payment(
        booking["id"], {"kind": "DEPOSIT", "amount_cents": 14400}, make_client_headers(client["id"])))
    bk = get_success_data(api_client.get_booking(booking["id"], SM))
    assert bk["amount_paid_cents"] == 14400, bk["amount_paid_cents"]
    assert bk["settlement_status"] == "DEPOSIT_PAID", bk["settlement_status"]


# ─── Corner: consistency_model ────────────────────────
def test_confirm_response_reflects_state_immediately():
    """PRD §3.2: "On success the booking's `hold_expires_at` is cleared to null and its `version`
    increments by one."
    PRD §3.2: "Confirmation is a `StudioManager` action that advances `schedule_status` from
    `HELD` to `CONFIRMED`."

    Design: Corner/consistency_model/confirm_response_reflects_state_immediately
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    res = api_client.confirm_booking(booking["id"], SM)
    confirmed = validate_success(res, 200)
    assert confirmed["schedule_status"] == "CONFIRMED", confirmed["schedule_status"]
    assert confirmed["hold_expires_at"] is None, confirmed["hold_expires_at"]
