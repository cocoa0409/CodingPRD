"""Booking-eligibility gauntlet: deposit gating (combinatorial three-input rule),
credit sufficiency, cross-entity membership-active dependency, and the no-show
strike accumulation that flips deposit gating."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_studio,
    set_clock,
    create_location,
    create_member,
    create_membership,
    create_and_activate_membership,
    create_frozen_membership,
    book_reservation,
    get_member,
    get_membership,
    get_room_version,
    get_membership_version,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]


def _book_payload(studio, member, **over):
    p = {
        "member_id": member["id"],
        "location_id": studio["loc"]["id"],
        "room_id": studio["room"]["id"],
        "technician_id": studio["tech"]["id"],
        "service_type_id": studio["svc"]["id"],
        "start_utc": "2026-06-17T10:00:00Z",
        "payment_method": "CREDIT",
        "expected_room_version": studio["room"]["version"],
    }
    p.update(over)
    return p


def test_deposit_required_when_two_strikes_credit_nonunlimited(api):
    """PRD 3.5: "A booking is forced to use a deposit when three conditions hold
    together: the member's `no_show_strike_count` is at least 2, the
    `payment_method` is `CREDIT`, and the membership's `tier` is not `UNLIMITED`.
    When all three are true, the credit booking is rejected with
    `ERR_DEPOSIT_REQUIRED`".

    A PLUS member with exactly 2 active strikes is rejected ERR_DEPOSIT_REQUIRED
    on a CREDIT booking (the non-linear AND of three inputs).

    Design: Difficulty/combinatorial_formula/deposit_gate_combinatorial_three_inputs
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Strikeville", "state_code": "TX",
                            "deposit_required_cents": 1000},
        service_overrides={"name": "Brow", "duration_minutes": 30,
                           "list_price_cents": 2000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    # Build exactly 2 ACTIVE no-show strikes via two DEPOSIT bookings + no-show.
    rv = studio["room"]["version"]
    r1 = book_reservation(member=member, location_id=studio["loc"]["id"],
                          room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                          service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                          payment_method="DEPOSIT", expected_room_version=rv, booked_by="frontdesk")
    rv = get_room_version(studio["room"]["id"])
    r2 = book_reservation(member=member, location_id=studio["loc"]["id"],
                          room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                          service_type_id=studio["svc"]["id"], start_utc="2026-06-16T11:00:00Z",
                          payment_method="DEPOSIT", expected_room_version=rv, booked_by="frontdesk")
    set_clock("2026-06-16T12:00:00Z")
    # Clock advance may auto-sweep both to NO_SHOW; ensure both are marked.
    api.mark_no_show_reservation(r1["id"], FRONT)
    api.mark_no_show_reservation(r2["id"], FRONT)

    member_now = get_member(member["id"])
    assert member_now["no_show_strike_count"] == 2, \
        f"Expected 2 active strikes, got {member_now['no_show_strike_count']}"

    rv = get_room_version(studio["room"]["id"])
    mv = get_membership_version(mbr["id"])
    resp = api.create_reservation(
        _book_payload(studio, member, start_utc="2026-06-17T10:00:00Z",
                      payment_method="CREDIT", membership_id=mbr["id"],
                      expected_room_version=rv, expected_membership_version=mv),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED.value)


def test_below_two_strikes_credit_booking_allowed(api):
    """PRD 3.5: "a member below the two-strike threshold books on credit
    normally."

    A PLUS member with only 1 active strike is below the deposit-gate threshold,
    so a CREDIT booking is accepted (boundary X-1 of the >=2 strike rule).

    Design: Difficulty/combinatorial_formula/deposit_gate_combinatorial_three_inputs
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Strikeville1", "state_code": "TX",
                            "deposit_required_cents": 1000},
        service_overrides={"name": "Brow", "duration_minutes": 30,
                           "list_price_cents": 2000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    rv = studio["room"]["version"]
    r1 = book_reservation(member=member, location_id=studio["loc"]["id"],
                          room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                          service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                          payment_method="DEPOSIT", expected_room_version=rv, booked_by="frontdesk")
    set_clock("2026-06-16T12:00:00Z")
    api.mark_no_show_reservation(r1["id"], FRONT)
    assert get_member(member["id"])["no_show_strike_count"] == 1

    rv = get_room_version(studio["room"]["id"])
    mv = get_membership_version(mbr["id"])
    data = validate_success(api.create_reservation(
        _book_payload(studio, member, start_utc="2026-06-17T10:00:00Z",
                      payment_method="CREDIT", membership_id=mbr["id"],
                      expected_room_version=rv, expected_membership_version=mv),
        make_member_headers(member["id"])), 201)
    assert data["booking_status"] == "BOOKED"
    assert data["settlement_status"] == "CREDIT_HELD"


def test_credit_booking_zero_balance_rejected(api):
    """PRD 3.4: "the booking is allowed only when that balance is at least the
    needed `credit_cost` — otherwise it is rejected with
    `ERR_INSUFFICIENT_CREDITS`."

    A BASIC membership whose 1 granted credit was consumed by a completed visit
    has balance 0; a credit_cost=1 booking is rejected ERR_INSUFFICIENT_CREDITS
    (zero-balance boundary).

    Design: Difficulty/boundary_precision_check/insufficient_credits_zero_balance_empty_pool
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Zerotown"},
        service_overrides={"name": "Nose", "duration_minutes": 15,
                           "list_price_cents": 1000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="BASIC",
                                         monthly_credit_grant=1, monthly_fee_cents=4000)
    rv = studio["room"]["version"]
    r1 = book_reservation(member=member, location_id=studio["loc"]["id"],
                          room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                          service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                          payment_method="CREDIT", expected_room_version=rv,
                          membership_id=mbr["id"], expected_membership_version=mbr["version"],
                          booked_by="frontdesk")
    set_clock("2026-06-16T09:45:00Z")
    api.check_in_reservation(r1["id"], FRONT)
    api.complete_reservation(r1["id"], FRONT)
    assert get_membership(mbr["id"])["credit_balance"] == 0

    rv = get_room_version(studio["room"]["id"])
    mv = get_membership_version(mbr["id"])
    resp = api.create_reservation(
        _book_payload(studio, member, start_utc="2026-06-17T10:00:00Z",
                      payment_method="CREDIT", membership_id=mbr["id"],
                      expected_room_version=rv, expected_membership_version=mv),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS.value)
    assert get_membership(mbr["id"])["credit_balance"] == 0


def test_credit_booking_with_one_credit_succeeds(api):
    """PRD 3.4: "the booking is allowed only when that balance is at least the
    needed `credit_cost`".

    The X+1 side of the zero-balance boundary: a BASIC membership with balance 1
    and a credit_cost=1 service books successfully (balance exactly meets need),
    confirming the rejection is specific to the empty pool.

    Design: Difficulty/boundary_precision_check/insufficient_credits_zero_balance_empty_pool
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Onetown"},
        service_overrides={"name": "Nose", "duration_minutes": 15,
                           "list_price_cents": 1000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="BASIC",
                                         monthly_credit_grant=1, monthly_fee_cents=4000)
    assert get_membership(mbr["id"])["credit_balance"] == 1
    data = validate_success(api.create_reservation(
        _book_payload(studio, member, start_utc="2026-06-16T10:00:00Z",
                      payment_method="CREDIT", membership_id=mbr["id"],
                      expected_room_version=studio["room"]["version"],
                      expected_membership_version=mbr["version"]),
        make_member_headers(member["id"])), 201)
    assert data["booking_status"] == "BOOKED"
    assert data["credits_held"] == 1


def test_no_show_forfeits_deposit_settlement(api):
    """PRD 3.6: "Marking a no-show ... moves the settlement axis to `FORFEITED`
    (a deposit is forfeited, held credits are forfeited with no `REFUND`),
    increments the member's `no_show_strike_count`".

    Marking a BOOKED DEPOSIT reservation NO_SHOW drives the settlement axis to
    FORFEITED and increments the strike count — the forfeiture leg of the
    no-show cascade that drives strike accumulation.

    Design: Difficulty/transitive_cascade/no_show_strike_depth2_deposit_gate_flip
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Strike2b", "state_code": "TX",
                            "deposit_required_cents": 1000},
        service_overrides={"name": "Lip", "duration_minutes": 15,
                           "list_price_cents": 1200, "credit_cost": 1},
    )
    member = studio["member"]
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="DEPOSIT", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T10:20:00Z")
    api.mark_no_show_reservation(res["id"], FRONT)
    after = validate_success(api.get_reservation(res["id"], FRONT), 200)
    assert after["booking_status"] == "NO_SHOW"
    assert after["settlement_status"] == "FORFEITED"
    assert get_member(member["id"])["no_show_strike_count"] == 1


def test_credit_booking_against_frozen_membership_rejected(api):
    """PRD 3.4: "for a credit booking, the membership must be `ACTIVE` — a
    `FROZEN`, `PAST_DUE`, `PENDING`, or `CANCELLED` membership is rejected with
    `ERR_MEMBERSHIP_NOT_ACTIVE`."

    A CREDIT reservation referencing a FROZEN membership is rejected
    ERR_MEMBERSHIP_NOT_ACTIVE (cross-entity Reservation -> Membership state
    dependency).

    Design: Difficulty/cross_entity_state_dependency/credit_booking_requires_membership_active
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Crossdep"},
        service_overrides={"name": "Back", "duration_minutes": 45,
                           "list_price_cents": 5500, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_frozen_membership(member["id"], freeze_days=30, tier="PLUS",
                                   monthly_credit_grant=8, monthly_fee_cents=6000)
    assert mbr["status"] == "FROZEN"
    mv = get_membership_version(mbr["id"])
    resp = api.create_reservation(
        _book_payload(studio, member, start_utc="2026-06-16T10:00:00Z",
                      payment_method="CREDIT", membership_id=mbr["id"],
                      expected_room_version=studio["room"]["version"],
                      expected_membership_version=mv),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_credit_booking_against_pending_membership_rejected(api):
    """PRD 3.4: "for a credit booking, the membership must be `ACTIVE` — a
    `FROZEN`, `PAST_DUE`, `PENDING`, or `CANCELLED` membership is rejected with
    `ERR_MEMBERSHIP_NOT_ACTIVE`."

    A CREDIT reservation referencing a never-activated PENDING membership is
    rejected ERR_MEMBERSHIP_NOT_ACTIVE — a second non-ACTIVE status confirming
    the cross-entity state dependency is not specific to FROZEN.

    Design: Difficulty/cross_entity_state_dependency/credit_booking_requires_membership_active
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Crossdep2"},
        service_overrides={"name": "Back", "duration_minutes": 45,
                           "list_price_cents": 5500, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_membership(member["id"], tier="PLUS", monthly_credit_grant=8,
                            monthly_fee_cents=6000)
    assert mbr["status"] == "PENDING"
    resp = api.create_reservation(
        _book_payload(studio, member, start_utc="2026-06-16T10:00:00Z",
                      payment_method="CREDIT", membership_id=mbr["id"],
                      expected_room_version=studio["room"]["version"],
                      expected_membership_version=mbr["version"]),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_second_no_show_raises_strike_count_to_two(api):
    """PRD 3.6: "Marking a no-show mints a `NoShowStrike` of kind `NO_SHOW`,
    moves the settlement axis to `FORFEITED` (a deposit is forfeited, held
    credits are forfeited with no `REFUND`), increments the member's
    `no_show_strike_count`".

    With one prior active strike, marking a second BOOKED reservation NO_SHOW
    drives it to NO_SHOW/FORFEITED and raises no_show_strike_count to 2 (the
    depth-2 propagation that henceforth gates credit bookings).

    Design: Difficulty/transitive_cascade/no_show_strike_depth2_deposit_gate_flip
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Strike2town", "state_code": "TX",
                            "deposit_required_cents": 1000},
        service_overrides={"name": "Lip", "duration_minutes": 15,
                           "list_price_cents": 1200, "credit_cost": 1},
    )
    member = studio["member"]
    rv = studio["room"]["version"]
    r1 = book_reservation(member=member, location_id=studio["loc"]["id"],
                          room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                          service_type_id=studio["svc"]["id"], start_utc="2026-06-16T09:00:00Z",
                          payment_method="DEPOSIT", expected_room_version=rv, booked_by="frontdesk")
    rv = get_room_version(studio["room"]["id"])
    r2 = book_reservation(member=member, location_id=studio["loc"]["id"],
                          room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                          service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                          payment_method="DEPOSIT", expected_room_version=rv, booked_by="frontdesk")
    set_clock("2026-06-16T12:00:00Z")
    api.mark_no_show_reservation(r1["id"], FRONT)
    api.mark_no_show_reservation(r2["id"], FRONT)

    r2_after = validate_success(api.get_reservation(r2["id"], FRONT), 200)
    assert r2_after["booking_status"] == "NO_SHOW"
    assert r2_after["settlement_status"] == "FORFEITED"
    assert get_member(member["id"])["no_show_strike_count"] == 2
