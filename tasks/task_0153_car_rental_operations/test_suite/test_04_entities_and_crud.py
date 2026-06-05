"""Entity creation, computed-field initialization, and request well-formedness."""
from test_helpers import (
    validate_success, validate_error,
    make_fleet_manager_headers, make_rental_agent_headers,
    NON_EXISTENT_UUID,
    create_location, create_econ_class, create_member,
    assert_location, assert_vehicle_class, assert_vehicle,
    get_vehicle_class,
    create_vehicle_class_payload,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId

FM = make_fleet_manager_headers()
RA = make_rental_agent_headers()


def test_create_location_returns_201_with_all_fields(api):
    """PRD §2.4: "an `id` that is a server-minted UUID with no type prefix; a
    `created_at` ISO 8601 UTC timestamp with three fractional digits recording
    first creation ... and an integer `version` that starts at its initial value
    and increments by one on every mutation."

    Design: Corner/entities/create_location_returns_201_with_all_fields
    """
    data = validate_success(api.create_location(f.create_location_payload(
        code="JFK", name="New York JFK", one_way_drop_fee_cents=7000,
        young_driver_surcharge_per_day_cents=2000,
    ), FM), 201)
    assert_location(data)
    assert data["code"] == "JFK"
    assert data["one_way_drop_fee_cents"] == 7000
    assert data["version"] == 1


def test_create_vehicle_class_initializes_counts_to_zero(api):
    """PRD §3.1: "A newly created class starts with both its denormalized
    `total_count` and `available_count` at zero."

    Design: Corner/entities/create_vehicle_class_initializes_counts_to_zero
    """
    data = validate_success(api.create_vehicle_class(create_vehicle_class_payload(
        code="SUVX", tier_rank=3, daily_rate_cents=8000, weekly_rate_cents=49000,
        included_miles_per_day=150, overage_per_mile_cents=35,
        ldw_per_day_cents=2000, pai_per_day_cents=1000,
    ), FM), 201)
    assert_vehicle_class(data)
    assert data["total_count"] == 0
    assert data["available_count"] == 0


def test_add_vehicle_reconciles_class_counts_to_one(api):
    """PRD §3.1: "creating it triggers the availability reconciliation on its
    class so both counts reflect the new row."

    Design: Corner/entities/add_vehicle_bumps_class_counts_to_one
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    veh = validate_success(api.create_vehicle(
        f.create_vehicle_payload(loc["id"], cls["id"], plate="LAX-001"), FM,
    ), 201)
    assert_vehicle(veh)
    assert veh["status"] == "AVAILABLE"
    cls_after = get_vehicle_class(cls["id"], api=api)
    assert cls_after["total_count"] == 1
    assert cls_after["available_count"] == 1


def test_get_vehicle_nonexistent_returns_not_found(api):
    """PRD §2.6: "the system validates existence left to right and rejects the
    first missing reference with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_vehicle_nonexistent_returns_not_found
    """
    resp = api.get_vehicle(NON_EXISTENT_UUID, FM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_reservation_missing_class_id_returns_invalid_request(api):
    """PRD §2.7: "(4) well-formedness of the request body — required fields
    present, enumerated values in range, `dropoff_at` strictly after `pickup_at`,
    and constrained integers non-negative — rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_reservation_missing_required_field_returns_invalid_request
    """
    loc = create_location(api=api)
    member = create_member(api=api)
    # class_id deliberately omitted.
    payload = {
        "member_id": member["id"],
        "pickup_location_id": loc["id"],
        "dropoff_location_id": loc["id"],
        "pickup_at": "2026-07-01T10:00:00Z",
        "dropoff_at": "2026-07-04T10:00:00Z",
    }
    resp = api.create_reservation(payload, RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_reservation_dropoff_before_pickup_returns_invalid_request(api):
    """PRD §2.7: "(4) well-formedness of the request body — required fields
    present, enumerated values in range, `dropoff_at` strictly after `pickup_at`,
    and constrained integers non-negative — rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_reservation_dropoff_before_pickup_returns_invalid_request
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    member = create_member(api=api)
    payload = f.create_reservation_payload(
        member["id"], loc["id"], loc["id"], cls["id"],
        "2026-07-04T10:00:00Z", "2026-07-01T10:00:00Z",
    )
    resp = api.create_reservation(payload, RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_reservation_rental_days_floor_of_one_for_sub_day(api):
    """PRD §3.3: "Its billable `rental_days` is computed as the number of 24-hour
    spans between pickup and dropoff, rounded up to the next whole day, with a
    floor of one day — so any rental, however short, bills at least one day."

    Design: Corner/entities/reservation_rental_days_min_one_for_sub_day
    """
    loc = create_location(api=api)
    cls = create_econ_class(api=api)
    member = create_member(api=api)
    res = validate_success(api.create_reservation(f.create_reservation_payload(
        member["id"], loc["id"], loc["id"], cls["id"],
        "2026-07-01T10:00:00Z", "2026-07-01T16:00:00Z",
    ), RA), 201)
    assert res["rental_days"] == 1
