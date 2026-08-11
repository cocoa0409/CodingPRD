"""Client registration, service addresses and the humidity record."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_climate_reading,
    assert_client,
    assert_climate_reading,
    assert_location,
    client_payload,
    is_valid_uuid,
    location_payload,
    new_client,
    new_location,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


def test_client_registration_applies_declared_defaults(api):
    """PRD 3.1: "The `client_type` may be supplied and defaults to `INDIVIDUAL`; the
    alternatives are `INSTITUTION` and `DEALER`, and the choice reaches surprisingly
    far — it selects the discount applied to every quote line and it selects which of
    three deposit branches the shop asks for."
    PRD 3.1: "New clients begin with `status` `ACTIVE` and `account_credit_cents` of 0."
    PRD 2.4: "Every resource carries a server-minted `id` that is a UUID with no type
    prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits."
    PRD 2.4: "Most resources additionally carry `updated_at` (same format, refreshed on
    every mutation) and `version`, an integer that starts at 1 on creation and
    increments by exactly 1 on each mutation of that row."

    Design: Corner/entities/client_creation_applies_defaults_and_system_fields
    """
    payload = client_payload(display_name="Minimal Client", home_zone_code="ZONE_C")
    payload.pop("client_type", None)

    data = validate_success(api.create_client(payload, MANAGER), 201)

    assert_client(data)
    assert data["client_type"] == "INDIVIDUAL"
    assert data["status"] == "ACTIVE"
    assert data["account_credit_cents"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]) and "_" not in data["id"]


def test_location_create_without_zone_code_is_rejected(api):
    """PRD 2.8: "**Body shape.** The request body must parse as a JSON object and every
    required input field of the operation must be present and non-null. Otherwise
    `ERR_VALIDATION` (400)."
    PRD 3.1: "Creating one supplies the owning `client_id`, a human `label` such as
    "Main Hall" or "Residence", a `zone_code`, an `address_key`, and a
    `distance_miles_from_shop` that must not be negative."

    Design: Corner/entities/location_create_missing_required_field_returns_invalid_request
    """
    client = new_client()
    payload = location_payload(client["id"], label="No Zone")
    payload.pop("zone_code")

    response = api.create_location(payload, MANAGER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows, _ = validate_paginated(
        api.list_locations(MANAGER, params={"client_id": client["id"]})
    )
    assert rows == [], "a rejected create must not leave a Location behind"


def test_location_create_with_undeclared_zone_code_is_rejected(api):
    """PRD 2.8: "**Enum membership.** Every enum-typed input field must carry a declared
    member of that enum. This routing list is exhaustive and closed: `client_type`,
    `home_zone_code`, `zone_code`, `instrument_class`, `usage_tier`, `service_type`,
    `to_condition_status`, `to_custody_status`, `to_status`, `certification_level`,
    `part_type`, `decision`, `void_reason`, status filters and `overdue_tier` filters
    route here, and **no other field does**. Otherwise `ERR_INVALID_ENUM` (400)."

    Design: Corner/entities/location_create_with_invalid_zone_enum_returns_invalid_enum
    """
    client = new_client()
    response = api.create_location(
        location_payload(client["id"], label="Bad Zone", zone_code="ZONE_Z"), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)


def test_location_stair_flights_above_eight_is_out_of_range(api):
    """PRD 2.8: "**Numeric and temporal ranges.** `stair_flights` must be an integer
    from 0 through 8"; the same rung ends "Otherwise `ERR_VALUE_OUT_OF_RANGE` (400)."
    PRD 3.1: "Three further attributes may be supplied and otherwise take their
    defaults: `stair_flights`, an integer from 0 through 8 that defaults to 0;
    `has_service_elevator`, defaulting to false; and `climate_controlled`, defaulting
    to false."

    Design: Corner/entities/location_stair_flights_above_eight_returns_value_out_of_range
    """
    client = new_client()

    rejected = api.create_location(
        location_payload(client["id"], label="Too Many Stairs", stair_flights=9), MANAGER
    )
    validate_error(rejected, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)

    accepted = validate_success(
        api.create_location(
            location_payload(client["id"], label="Eight Stairs", stair_flights=8),
            MANAGER,
        ),
        201,
    )
    assert_location(accepted)
    assert accepted["stair_flights"] == 8, "the inclusive upper bound 8 is accepted"


def test_location_create_with_unresolvable_client_is_not_found(api):
    """PRD 2.8: "A `client_id`, `consignor_client_id` or `buyer_client_id` that does not
    resolve yields `ERR_CLIENT_NOT_FOUND` (404)."

    Design: Corner/errors/location_create_with_unknown_client_returns_client_not_found
    """
    response = api.create_location(
        location_payload("00000000-0000-4000-8000-000000000001", label="Ghost"), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_climate_reading_is_append_only_and_bands_inclusively(api):
    """PRD 2.4: "Two entities are the exception: a `ClimateReading` and a `LedgerEntry`
    carry only `id` and `created_at` — they have no `updated_at` and no `version`,
    because both are append-only records of something that happened and are never
    edited after the fact."
    PRD 3.1: "Each reading is stamped with `in_band`, true when its
    `relative_humidity_pct` sits within the inclusive band from 35.0 through 55.0."
    PRD 3.1: "When fewer than 4 readings fall in the window the address is not judged at
    all and `out_of_band_flag` is false."

    Design: Corner/entities/climate_reading_is_append_only_with_no_version_field
    """
    client = new_client()
    location = new_location(client["id"], label="Room")

    data = validate_success(
        api.create_climate_reading(
            {
                "location_id": location["id"],
                "recorded_at_utc": "2026-04-10T08:00:00Z",
                "relative_humidity_pct": 35.0,
                "temperature_f": 66.0,
            },
            MANAGER,
        ),
        201,
    )

    assert_climate_reading(data)
    assert "version" not in data and "updated_at" not in data
    assert data["in_band"] is True, "35.0 sits exactly on the inclusive lower bound"

    location_now = validate_success(api.get_location(location["id"], MANAGER))
    assert location_now["readings_in_window"] == 1
    assert location_now["out_of_band_flag"] is False


def test_pagination_limit_above_one_hundred_is_rejected(api):
    """PRD 2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100;
    `offset` defaults to 0 and has a minimum of 0. A `limit` outside 1 through 100, a
    negative `offset`, or a non-integer value for either is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/pagination_limit_above_hundred_returns_invalid_pagination
    """
    rejected = api.list_clients(MANAGER, params={"limit": 101, "offset": 0})
    validate_error(rejected, ApiErrorId.ERR_INVALID_PAGINATION.value)

    accepted = api.list_clients(MANAGER, params={"limit": 100, "offset": 0})
    assert accepted.status_code == 200, "limit 100 sits on the inclusive maximum"


def test_climate_ratio_of_exactly_one_quarter_leaves_the_address_in_band(api):
    """PRD 3.1: "Otherwise the flag is true exactly when `out_of_band_count` divided by
    `readings_in_window` is **strictly greater** than 0.25 — a ratio of exactly one
    quarter does not trip it, so one bad reading out of four leaves the address in good
    standing while two out of seven does not."
    PRD 3.1: "`readings_in_window` records how many readings fell inside it;
    `out_of_band_count` records how many of those had a `relative_humidity_pct` below
    35.0 or above 55.0."

    Design: Difficulty/boundary_precision_check/climate_ratio_exactly_one_quarter_does_not_trip_the_flag
    """
    client = new_client(client_type="INSTITUTION")
    location = new_location(client["id"], label="Archive Room", climate_controlled=False)
    for day in ("01", "02", "03"):
        add_climate_reading(location["id"], f"2026-04-{day}T12:00:00Z", 45.0)

    fourth = validate_success(
        api.create_climate_reading(
            {
                "location_id": location["id"],
                "recorded_at_utc": "2026-04-04T12:00:00Z",
                "relative_humidity_pct": 20.0,
                "temperature_f": 68.0,
            },
            MANAGER,
        ),
        201,
    )
    assert fourth["in_band"] is False, "20.0 falls below the 35.0 lower band bound"

    location_now = validate_success(api.get_location(location["id"], MANAGER))
    assert location_now["readings_in_window"] == 4
    assert location_now["out_of_band_count"] == 1
    assert location_now["out_of_band_flag"] is False, (
        "1 of 4 is exactly 0.25, which is not strictly greater than 0.25"
    )


def test_climate_ratio_above_one_quarter_trips_the_flag(api):
    """PRD 3.1: "Otherwise the flag is true exactly when `out_of_band_count` divided by
    `readings_in_window` is **strictly greater** than 0.25 — a ratio of exactly one
    quarter does not trip it, so one bad reading out of four leaves the address in good
    standing while two out of seven does not."
    PRD 3.1: "The evaluation window is the 180 days ending at the logical clock, and
    both bounds are inclusive: a reading is in the window when its `recorded_at_utc` is
    at or after the instant 180 days before the clock and at or before the clock itself."

    Design: Difficulty/boundary_precision_check/climate_ratio_exactly_one_quarter_does_not_trip_the_flag
    """
    client = new_client(client_type="INSTITUTION")
    location = new_location(client["id"], label="Archive Room", climate_controlled=False)
    for day in ("01", "02", "03"):
        add_climate_reading(location["id"], f"2026-04-{day}T12:00:00Z", 45.0)
    add_climate_reading(location["id"], "2026-04-04T12:00:00Z", 20.0)

    fifth = validate_success(
        api.create_climate_reading(
            {
                "location_id": location["id"],
                "recorded_at_utc": "2026-04-05T12:00:00Z",
                "relative_humidity_pct": 62.0,
                "temperature_f": 68.0,
            },
            MANAGER,
        ),
        201,
    )
    assert fifth["in_band"] is False, "62.0 rises above the 55.0 upper band bound"

    location_now = validate_success(api.get_location(location["id"], MANAGER))
    assert location_now["readings_in_window"] == 5
    assert location_now["out_of_band_count"] == 2
    assert location_now["out_of_band_flag"] is True, "2 of 5 is 0.4, above the threshold"
