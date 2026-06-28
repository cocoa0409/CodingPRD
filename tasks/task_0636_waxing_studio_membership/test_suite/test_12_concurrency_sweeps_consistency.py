"""Cross-cutting corners: optimistic-concurrency stale-version rejection (room
and membership), the clock-driven strike-expiry sweep, and immediate-consistency
visibility of a credit debit."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_studio,
    set_clock,
    create_location,
    create_service_type,
    create_room,
    create_technician,
    create_member,
    create_and_activate_membership,
    book_reservation,
    get_room_version,
    get_member,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_stale_room_version_on_second_booking_rejected(api):
    """PRD 2.6: "A request to create a reservation must carry
    `expected_room_version` as a required field whose value equals the current
    `version` of the target `Room` ... if any writer has advanced the room's
    `version` since the client last read it, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412), even when the new request would legitimately
    fill a different, non-overlapping slot."

    After a first booking advances Room.version to 2, a second create still
    carrying the pre-booking expected_room_version=1 is rejected ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_room_version_on_second_booking
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Occ")
    svc = create_service_type(name="QOcc", duration_minutes=30, list_price_cents=2000)
    room = create_room(loc["id"], label="ROcc")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TOcc")
    member = create_member(loc["id"])
    stale_version = room["version"]
    book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                     technician_id=tech["id"], service_type_id=svc["id"],
                     start_utc="2026-06-16T10:00:00Z", payment_method="WALK_IN",
                     expected_room_version=stale_version, booked_by="frontdesk")
    # Second create with the now-stale version, on a non-overlapping slot.
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T12:00:00Z", "payment_method": "WALK_IN",
        "expected_room_version": stale_version,
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_membership_version_on_credit_booking_rejected(api):
    """PRD 2.6: "When the reservation is paid by membership credit ... the request
    must additionally carry `expected_membership_version` ... Each successful
    credit debit advances the membership's `version`; a create that carries a
    membership version older than the membership's current `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412)".

    A first CREDIT booking debits the membership (version advances); a second
    create carrying the pre-debit expected_membership_version is rejected
    ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_membership_version_on_credit_booking
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "OccM"},
                          service_overrides={"name": "QOccM", "duration_minutes": 30,
                                             "list_price_cents": 3000, "credit_cost": 1})
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    stale_mbr_version = mbr["version"]
    book_reservation(member=member, location_id=studio["loc"]["id"],
                     room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                     service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                     payment_method="CREDIT", expected_room_version=studio["room"]["version"],
                     membership_id=mbr["id"], expected_membership_version=stale_mbr_version,
                     booked_by="frontdesk")
    fresh_room_version = get_room_version(studio["room"]["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": studio["loc"]["id"],
        "room_id": studio["room"]["id"], "technician_id": studio["tech"]["id"],
        "service_type_id": studio["svc"]["id"], "start_utc": "2026-06-16T12:00:00Z",
        "payment_method": "CREDIT", "membership_id": mbr["id"],
        "expected_room_version": fresh_room_version,
        "expected_membership_version": stale_mbr_version,
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_strike_expiry_sweep_decrements_count(api):
    """PRD 3.8: "The strike-expiry sweep finds every `ACTIVE` `NoShowStrike`
    whose `created_at` plus 90 days has been reached and moves it to `EXPIRED`,
    recomputing the affected member's `no_show_strike_count`".

    A member's lone ACTIVE strike (minted ~2026-06-16) is expired when the clock
    advances past created_at+90 days, dropping no_show_strike_count to 0.

    Design: Corner/cross_cutting_complexity_layers/strike_expiry_sweep_on_clock_advance
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z",
                          location_overrides={"name": "Exp", "deposit_required_cents": 1000},
                          service_overrides={"name": "QEx", "duration_minutes": 15,
                                             "list_price_cents": 1200})
    member = studio["member"]
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="DEPOSIT", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T10:20:00Z")
    api.mark_no_show_reservation(res["id"], FRONT)
    assert get_member(member["id"])["no_show_strike_count"] == 1
    set_clock("2026-09-20T00:00:00Z")  # > created_at + 90 days
    assert get_member(member["id"])["no_show_strike_count"] == 0


def test_credit_debit_visible_immediately(api):
    """PRD 2.5: "Whenever an underlying record changes, the owning resource's
    derived fields are recomputed".
    PRD 3.4: "the system writes a `DEBIT` ledger entry whose `delta_credits` is
    the negative of the service's `credit_cost`".

    Booking a credit_cost=1 CREDIT reservation from an 8-credit membership makes
    the membership read immediately afterward show credit_balance==7.

    Design: Corner/consistency_model/credit_debit_visible_in_same_response
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Imm"},
                          service_overrides={"name": "QImm", "duration_minutes": 30,
                                             "list_price_cents": 3000, "credit_cost": 1})
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    book_reservation(member=member, location_id=studio["loc"]["id"],
                     room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                     service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                     payment_method="CREDIT", expected_room_version=studio["room"]["version"],
                     membership_id=mbr["id"], expected_membership_version=mbr["version"],
                     booked_by="frontdesk")
    after = validate_success(api.get_membership(mbr["id"], make_member_headers(member["id"])), 200)
    assert after["credit_balance"] == 7
