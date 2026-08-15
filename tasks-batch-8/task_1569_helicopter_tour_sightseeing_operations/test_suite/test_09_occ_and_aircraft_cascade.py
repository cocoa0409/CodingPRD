"""Optimistic concurrency (PRD §2.6) and the aircraft-ground cascade."""
from test_helpers import (
    ApiErrorId,
    confirm_booking,
    create_aircraft,
    create_booking,
    create_flight,
    create_pilot,
    get_base,
    get_booking,
    get_flight,
    list_credits_for_booking,
    open_boarding,
    passenger_entry,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import create_base

DISP = TEST_USERS["dispatcher_headers"]
AGENT = TEST_USERS["booking_agent_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def test_occ_flight_assignment_stale_version(api):
    """PRD §2.6: "Reassigning a flight's crew (`PATCH
    /flights/{id}/assignment`) requires `expected_flight_version`, matched
    against the flight's current `version`. Reassignment is legitimate
    whenever the flight is `SCHEDULED` or `DELAYED`, so a client whose view
    predates another landed assignment must be told its view is stale rather
    than silently overwrite it."
    PRD §2.6: "if that value does not match the parent resource's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_flight_assignment_stale_version
    """
    env = setup_ops_env()
    a2 = create_aircraft(tail_number="N2")
    p2 = create_pilot(display_name="Pat Two", certificate_no="C2")
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    observed_version = flight["version"]

    ok = validate_success(
        api.update_flight_assignment(
            flight["id"],
            {"expected_flight_version": observed_version,
             "pilot_id": p2["id"]},
            DISP,
        )
    )
    assert ok["pilot_id"] == p2["id"]
    assert ok["version"] == observed_version + 1, "OCC write increments version"

    # Replaying the pre-mutation version is stale now.
    resp = api.update_flight_assignment(
        flight["id"],
        {"expected_flight_version": observed_version,
         "aircraft_id": a2["id"]},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_flight(flight["id"])
    assert after["aircraft_id"] == env["aircraft"]["id"], "stale write applied nothing"
    assert after["version"] == observed_version + 1


def test_occ_close_manifest_stale_version(api):
    """PRD §2.6: "Closing a manifest (`POST /flights/{id}/close-manifest`)
    requires `expected_flight_version`, because interim flight mutations —
    assignment changes, delays — invalidate the weight-and-balance picture
    the closer computed from."
    PRD §2.6: "if that value does not match the parent resource's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "A successful close freezes `manifested_fuel_lb`,
    `actual_gross_weight_lb`, `actual_cg_in`, and
    `manifested_passenger_count` — the count of checked-in passengers on the
    manifested bookings — moves every CHECKED_IN booking of the flight to
    MANIFESTED, and increments the flight's `version` by one."

    Design: Corner/complexity_layers/occ_close_manifest_stale_version
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    open_boarding(flight["id"])
    current_version = get_flight(flight["id"])["version"]

    resp = api.close_manifest(
        flight["id"], {"expected_flight_version": current_version - 1}, DISP
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_flight(flight["id"])["status"] == "BOARDING"

    closed = validate_success(
        api.close_manifest(
            flight["id"], {"expected_flight_version": current_version}, DISP
        )
    )
    assert closed["status"] == "MANIFEST_CLOSED"
    assert closed["version"] == current_version + 1
    # Empty manifest: budget 2600-1500-0 == 1100 >= fuel_required 300.
    assert closed["manifested_fuel_lb"] == 300


def test_occ_booking_move_stale_version(api):
    """PRD §2.6: "Moving a booking to another flight
    (`POST /bookings/{id}/move`) requires `expected_booking_version`, since
    interim mutations such as credit applications or a confirm change the
    settlement base the mover priced from."
    PRD §2.6: "if that value does not match the parent resource's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_booking_move_stale_version
    """
    env = setup_ops_env()
    f1 = create_flight(env, "2026-08-05T14:00:00Z")
    f2 = create_flight(env, "2026-08-06T14:00:00Z")
    b1 = create_booking(f1["id"], [passenger_entry("P0", 150)])
    version_at_create = b1["version"]
    confirm_booking(b1["id"], b1["quoted_total_cents"])  # version advances

    resp = api.move_booking(
        b1["id"],
        {"new_flight_id": f2["id"],
         "expected_booking_version": version_at_create},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # Same route, weekday, no season -> identical quote -> zero delta, so no
    # additional_card_cents is required.
    moved = validate_success(
        api.move_booking(
            b1["id"],
            {"new_flight_id": f2["id"],
             "expected_booking_version": version_at_create + 1},
            AGENT,
        )
    )
    assert moved["status"] == "CONFIRMED"
    assert moved["flight_id"] == f2["id"]
    assert moved["version"] == version_at_create + 2
    assert moved["quoted_total_cents"] == 25000
    assert moved["paid_cents"] == 25000


def test_occ_base_config_stale_version(api):
    """PRD §2.6: "Updating base configuration (`PATCH /bases/{id}`) requires
    `expected_base_version`, so two operators cannot unknowingly overwrite
    each other's regulatory settings."
    PRD §2.6: "if that value does not match the parent resource's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "Base configuration is mutable afterward through the
    OCC-guarded update described in §2.6, which increments the base's
    `version`."

    Design: Corner/complexity_layers/occ_base_config_stale_version
    """
    base = create_base()
    observed_version = base["version"]

    ok = validate_success(
        api.update_base(
            base["id"],
            {"expected_base_version": observed_version,
             "hold_expire_minutes": 45},
            OPS,
        )
    )
    assert ok["hold_expire_minutes"] == 45
    assert ok["version"] == observed_version + 1

    resp = api.update_base(
        base["id"],
        {"expected_base_version": observed_version,
         "hold_expire_minutes": 50},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_base(base["id"], headers=OPS)
    assert after["hold_expire_minutes"] == 45, "second update never applied"
    assert after["version"] == observed_version + 1


def test_aircraft_ground_cascade_cancels_boarding_flight(api):
    """PRD §3.1: "Grounding is the heavier hammer: grounding an AVAILABLE
    aircraft cancels every one of its flights in SCHEDULED, DELAYED,
    BOARDING, or MANIFEST_CLOSED departing now or later, driving each to
    CANCELLED_OPS with `cancel_reason` AIRCRAFT_GROUNDED and firing the
    booking cascade of §3.8, while grounding from IN_MAINTENANCE fires no
    cascade because no such future flights can exist."
    PRD §3.8: "the bookings move the same way: HELD bookings become EXPIRED
    with no refund; CONFIRMED and CHECKED_IN bookings become CREDITED, their
    `credited_cents` set to `paid_cents`, and a `RebookingCredit` is minted
    for `paid_cents` plus `credits_applied_cents`"

    Design: Corner/state_machines/aircraft_ground_cascade_cancels_boarding_flight
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])
    confirm_booking(booking["id"], 25000)
    open_boarding(flight["id"])

    grounded = validate_success(
        api.aircraft_event(env["aircraft"]["id"], {"event_type": "GROUND"}, OPS)
    )
    assert grounded["status"] == "GROUNDED"

    f_after = get_flight(flight["id"])
    assert f_after["status"] == "CANCELLED_OPS"
    assert f_after["cancel_reason"] == "AIRCRAFT_GROUNDED"

    b_after = get_booking(booking["id"])
    assert b_after["status"] == "CREDITED"
    assert b_after["credited_cents"] == 25000

    credits = list_credits_for_booking(booking["id"])
    assert len(credits) == 1
    assert credits[0]["amount_cents"] == 25000
    assert credits[0]["status"] == "ISSUED"
