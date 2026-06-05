"""Cross-entity state dependencies, vehicle/location overlap rules, and the
validation-priority conflicts that pin which error wins when two checks fail.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    make_fleet_manager_headers, make_rental_agent_headers,
    create_location, create_econ_class, create_vehicle, create_member,
    create_reservation, confirm_reservation, hold_vehicle, set_clock,
    set_member_loyalty,
    setup_fleet, setup_confirmed_reservation, setup_open_agreement,
    get_vehicle,
    create_vehicle_class_payload,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_return_to_service_blocked_while_incident_filed(api):
    """PRD §3.8: "A `FleetManager` may also return a `MAINTENANCE` vehicle to
    service ... but only once no incident remains in `FILED` status on that
    vehicle's last agreement — every such incident must be `RESOLVED` or `VOID`,
    otherwise the return-to-service is rejected with `ERR_OPEN_INCIDENT`."

    Design: Difficulty/cross_entity_state_dependency/return_to_service_blocked_by_filed_incident
    """
    ctx = setup_open_agreement(api=api, reservation_overrides={"ldw_selected": True},
                               odometer_out=1000, fuel_out_eighths=8)
    agr, veh = ctx["agreement"], ctx["vehicle"]
    # FILED MAJOR incident -> damaged return -> vehicle goes to MAINTENANCE on close.
    validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MAJOR", 80000), RA,
    ), 201)
    validate_success(api.close_rental_agreement(agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA))

    veh_after = get_vehicle(veh["id"], api=api)
    assert veh_after["status"] == "MAINTENANCE"

    resp = api.return_vehicle_to_service(veh["id"], FM)
    validate_error(resp, ApiErrorId.ERR_OPEN_INCIDENT.value)


def test_resolve_incident_blocked_while_agreement_open(api):
    """PRD §3.8: "Resolving an incident is a `FleetManager` action moving it
    `FILED → RESOLVED`; it is permitted only once the parent agreement has
    reached a terminal state — `CLOSED` or `WRITE_OFF` — and is otherwise
    rejected with `ERR_AGREEMENT_STILL_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/incident_resolve_blocked_while_agreement_open
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(ctx["agreement"]["id"], "MINOR", 5000), RA,
    ), 201)
    resp = api.resolve_incident_report(inc["id"], FM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_STILL_OPEN.value)


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_hold_vehicle_double_booked_overlapping_window(api):
    """PRD §3.4: "if the vehicle's current active commitment — whether its
    existing `RESERVED` hold's reservation or its `ON_RENT` agreement's
    reservation — has a `[pickup_at, dropoff_at)` interval that overlaps the
    target reservation's interval, the hold is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`; half-open semantics again mean a shared boundary
    instant does not collide."

    Design: Difficulty/resource_temporal_overlap/vehicle_double_booked_half_open_overlap
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    fleet = setup_fleet(api=api, num_vehicles=2)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    veh1, veh2 = fleet["vehicles"]
    member = create_member(api=api)

    # veh1 -> ON_RENT for R1 [Jul1, Jul5).
    res1 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-05T10:00:00Z", api=api)
    confirm_reservation(res1["id"], api=api)
    hold_vehicle(veh1["id"], res1["id"], veh1["version"], api=api)
    validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res1["id"], veh1["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)

    # R2 [Jul3, Jul8) overlaps R1; confirmed via veh2 capacity.
    res2 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-03T10:00:00Z", "2026-07-08T10:00:00Z", api=api)
    confirm_reservation(res2["id"], api=api)
    veh1_now = get_vehicle(veh1["id"], api=api)
    resp = api.hold_vehicle(veh1["id"], {"reservation_id": res2["id"],
                                         "expected_vehicle_version": veh1_now["version"]}, RA)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value)
    assert get_vehicle(veh1["id"], api=api)["status"] == "ON_RENT"


def test_confirm_blocked_by_location_class_aggregate_capacity(api):
    """PRD §3.3: "counting the existing `CONFIRMED` and `PICKED_UP` reservations
    for the same pickup location and class whose scheduled `[pickup_at,
    dropoff_at)` interval overlaps this reservation's interval, that count must
    remain strictly below the location's fleet size for that class; if confirming
    would meet or exceed the fleet size, it is rejected with
    `ERR_LOCATION_CLASS_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/location_class_aggregate_capacity_overlap
    """
    fleet = setup_fleet(api=api, num_vehicles=1)  # fleet size 1 for ECON at LAX.
    loc, cls = fleet["location"], fleet["vehicle_class"]
    member = create_member(api=api)

    res1 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-05T10:00:00Z", api=api)
    confirm_reservation(res1["id"], api=api)
    res2 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-02T10:00:00Z", "2026-07-06T10:00:00Z", api=api)
    resp = api.confirm_reservation(res2["id"], RA)
    validate_error(resp, ApiErrorId.ERR_LOCATION_CLASS_CAPACITY.value)


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_confirm_member_blocked_beats_no_availability(api):
    """PRD §3.3: "First, the member must not be blocked: a member whose
    `no_show_strikes` has reached the limit of 3 (that is, three or more strikes)
    is rejected with `ERR_MEMBER_BLOCKED`. Second, the reserved class must have
    availability at the pickup location: its `available_count` must be at least
    1, else `ERR_NO_AVAILABILITY`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_member_blocked_beats_no_availability
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)  # no vehicles -> available_count 0.
    member = create_member(api=api, email="blocked@x.com", full_name="Block Ed")
    set_member_loyalty(member["id"], api=api, no_show_strikes=3)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    resp = api.confirm_reservation(res["id"], RA)
    # Both ERR_MEMBER_BLOCKED and ERR_NO_AVAILABILITY would fire; PRD §3.3 lists
    # the member-blocked check first ("First ... Second ..."), so it wins.
    validate_error(resp, ApiErrorId.ERR_MEMBER_BLOCKED.value)


def test_pickup_class_mismatch_or_grace_expired(api):
    """PRD §3.5: "pickup is allowed only within the grace window — the current
    server time must be at or before `hold_expires_at`, else the pickup is
    rejected with `ERR_GRACE_WINDOW_EXPIRED`."
    PRD §3.5: "The class/location match between vehicle and reservation is
    enforced here with `ERR_CLASS_MISMATCH` just as it is at hold time."

    PRD prose lists the grace check before the class match within §3.5, so a
    PRD-only implementer could faithfully report either error when both fail;
    the contract does not pin one over the other. Accept either.

    Design: Difficulty/priority_pair_validation_conflict/pickup_class_mismatch_beats_grace_window_expired
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    loc = create_location(api=api)
    cls_econ = create_econ_class(api=api)
    cls_lux = validate_success(api.create_vehicle_class(create_vehicle_class_payload(
        code="LUX", tier_rank=4, daily_rate_cents=9000, weekly_rate_cents=56000,
        included_miles_per_day=150, overage_per_mile_cents=40,
        ldw_per_day_cents=2500, pai_per_day_cents=1200,
    ), FM), 201)
    create_vehicle(loc["id"], cls_econ["id"], api=api, plate="LAX-ECON")
    veh_lux = create_vehicle(loc["id"], cls_lux["id"], api=api, plate="LAX-LUX")
    member = create_member(api=api)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls_econ["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirm_reservation(res["id"], api=api)
    set_clock("2026-07-01T14:00:00Z", api=api)  # past the grace window.

    resp = api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh_lux["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    )
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_CLASS_MISMATCH.value,
        ApiErrorId.ERR_GRACE_WINDOW_EXPIRED.value,
    ])


# ===========================================================================
# Queue A — second variants (each difficulty instance carries >=2 tests)
# ===========================================================================
def test_return_to_service_succeeds_once_incident_voided(api):
    """PRD §3.8: "A `FleetManager` may also return a `MAINTENANCE` vehicle to
    service, transitioning it `MAINTENANCE → AVAILABLE` and reconciling
    `available_count` upward, but only once no incident remains in `FILED`
    status on that vehicle's last agreement — every such incident must be
    `RESOLVED` or `VOID`"

    Design: Difficulty/cross_entity_state_dependency/return_to_service_blocked_by_filed_incident
    """
    ctx = setup_open_agreement(api=api, reservation_overrides={"ldw_selected": True},
                               odometer_out=1000, fuel_out_eighths=8)
    agr, veh = ctx["agreement"], ctx["vehicle"]
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MAJOR", 80000), RA,
    ), 201)
    validate_success(api.close_rental_agreement(agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA))
    assert get_vehicle(veh["id"], api=api)["status"] == "MAINTENANCE"
    # Void the FILED incident, then return-to-service becomes permitted.
    validate_success(api.void_incident_report(inc["id"], FM))
    returned = validate_success(api.return_vehicle_to_service(veh["id"], FM))
    assert returned["status"] == "AVAILABLE"


def test_resolve_incident_succeeds_after_agreement_closed(api):
    """PRD §3.8: "Resolving an incident is a `FleetManager` action moving it
    `FILED → RESOLVED`; it is permitted only once the parent agreement has
    reached a terminal state — `CLOSED` or `WRITE_OFF`"

    Design: Difficulty/cross_entity_state_dependency/incident_resolve_blocked_while_agreement_open
    """
    ctx = setup_open_agreement(api=api, odometer_out=1000, fuel_out_eighths=8)
    agr = ctx["agreement"]
    inc = validate_success(api.create_incident_report(
        f.create_incident_report_payload(agr["id"], "MINOR", 5000), RA,
    ), 201)
    validate_success(api.close_rental_agreement(agr["id"], {"odometer_in": 1100, "fuel_in_eighths": 8}, RA))
    resolved = validate_success(api.resolve_incident_report(inc["id"], FM))
    assert resolved["status"] == "RESOLVED"


def test_hold_double_booked_leaves_prior_commitment_intact(api):
    """PRD §3.4: "if the vehicle's current active commitment — whether its
    existing `RESERVED` hold's reservation or its `ON_RENT` agreement's
    reservation — has a `[pickup_at, dropoff_at)` interval that overlaps the
    target reservation's interval, the hold is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`"

    Asserts the rejected overlapping hold leaves the original ON_RENT
    commitment (its held_by clearance and agreement) untouched.

    Design: Difficulty/resource_temporal_overlap/vehicle_double_booked_half_open_overlap
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    fleet = setup_fleet(api=api, num_vehicles=2)
    loc, cls = fleet["location"], fleet["vehicle_class"]
    veh1, veh2 = fleet["vehicles"]
    member = create_member(api=api)

    # veh1 -> ON_RENT for R1 [Jul1, Jul5).
    res1 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-05T10:00:00Z", api=api)
    confirm_reservation(res1["id"], api=api)
    hold_vehicle(veh1["id"], res1["id"], veh1["version"], api=api)
    agr1 = validate_success(api.create_rental_agreement(
        f.create_rental_agreement_payload(res1["id"], veh1["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    ), 201)

    # Overlapping R2 [Jul3, Jul8) hold attempt is rejected.
    res2 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-03T10:00:00Z", "2026-07-08T10:00:00Z", api=api)
    confirm_reservation(res2["id"], api=api)
    veh1_now = get_vehicle(veh1["id"], api=api)
    resp = api.hold_vehicle(veh1["id"], {"reservation_id": res2["id"],
                                         "expected_vehicle_version": veh1_now["version"]}, RA)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value)

    # The original ON_RENT agreement and its vehicle are unchanged.
    after = get_vehicle(veh1["id"], api=api)
    assert after["status"] == "ON_RENT"
    assert api.get_rental_agreement(agr1["id"], RA).json()["data"]["status"] == "OPEN"


def test_confirm_non_overlapping_second_reservation_succeeds(api):
    """PRD §3.3: "Intervals are half-open, so two reservations that merely share
    a boundary instant do not overlap."

    Design: Difficulty/resource_temporal_overlap/location_class_aggregate_capacity_overlap
    """
    fleet = setup_fleet(api=api, num_vehicles=1)  # fleet size 1.
    loc, cls = fleet["location"], fleet["vehicle_class"]
    member = create_member(api=api)
    res1 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-01T10:00:00Z", "2026-07-05T10:00:00Z", api=api)
    confirm_reservation(res1["id"], api=api)
    # R2 [Jul5, Jul8) shares the boundary instant -> no overlap -> capacity allows confirm.
    res2 = create_reservation(member["id"], loc["id"], loc["id"], cls["id"],
                              "2026-07-05T10:00:00Z", "2026-07-08T10:00:00Z", api=api)
    confirmed2 = validate_success(api.confirm_reservation(res2["id"], RA))
    assert confirmed2["status"] == "CONFIRMED"


def test_confirm_unblocked_member_with_availability_succeeds(api):
    """PRD §3.3: "Second, the reserved class must have availability at the pickup
    location: its `available_count` must be at least 1, else
    `ERR_NO_AVAILABILITY`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_member_blocked_beats_no_availability
    """
    ctx = setup_confirmed_reservation(api=api, num_vehicles=1)
    # An unblocked member with one available vehicle confirms cleanly; neither
    # ERR_MEMBER_BLOCKED nor ERR_NO_AVAILABILITY fires.
    assert ctx["reservation"]["status"] == "CONFIRMED"


def test_pickup_class_mismatch_alone_within_grace_returns_mismatch(api):
    """PRD §3.5: "The class/location match between vehicle and reservation is
    enforced here with `ERR_CLASS_MISMATCH` just as it is at hold time."

    Isolated single-failure scenario (within grace) so only the class-mismatch
    check can fire — uniquely yielding ERR_CLASS_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/pickup_class_mismatch_beats_grace_window_expired
    """
    set_clock("2026-07-01T09:00:00Z", api=api)
    loc = create_location(api=api)
    cls_econ = create_econ_class(api=api)
    cls_lux = validate_success(api.create_vehicle_class(create_vehicle_class_payload(
        code="LUX", tier_rank=4, daily_rate_cents=9000, weekly_rate_cents=56000,
        included_miles_per_day=150, overage_per_mile_cents=40,
        ldw_per_day_cents=2500, pai_per_day_cents=1200,
    ), FM), 201)
    create_vehicle(loc["id"], cls_econ["id"], api=api, plate="LAX-ECON")
    veh_lux = create_vehicle(loc["id"], cls_lux["id"], api=api, plate="LAX-LUX")
    member = create_member(api=api)
    res = create_reservation(member["id"], loc["id"], loc["id"], cls_econ["id"],
                             "2026-07-01T10:00:00Z", "2026-07-04T10:00:00Z", api=api)
    confirm_reservation(res["id"], api=api)
    # Still within grace (now 09:00 < hold_expires 12:00); only the class mismatch can fire.
    resp = api.create_rental_agreement(
        f.create_rental_agreement_payload(res["id"], veh_lux["id"], odometer_out=1000, fuel_out_eighths=8), RA,
    )
    validate_error(resp, ApiErrorId.ERR_CLASS_MISMATCH.value)
