"""Response envelope, resource creation defaults, computed fields, listing."""
from test_helpers import (
    ApiErrorId,
    assert_base,
    assert_flight,
    assert_instant_equals,
    assert_weather_observation,
    create_base_payload,
    create_booking,
    create_flight,
    create_route_payload,
    get_base,
    is_iso8601_timestamp,
    is_valid_uuid,
    passenger_entry,
    parse_instant,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers.factories import create_pilot_payload
from test_helpers.fixtures import create_base, create_pilot, create_route

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
AGENT = TEST_USERS["booking_agent_headers"]


def test_response_envelope_success_and_error_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    base = create_base()

    resp = api.get_base(base["id"], DISP)
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"] == base["id"]

    resp = api.list_routes(DISP)
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "array"
    meta = body["meta"]
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 0 and meta["has_more"] is False
    assert body["data"] == []

    resp = api.get_base("00000000-0000-4000-8000-000000000000", DISP)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_base_creation_applies_defaults(api):
    """PRD §3.1: "Weather thresholds carry defaults used when the create
    payload omits them: `weather_ceiling_min_ft` defaults to 1000 feet,
    `weather_visibility_min_sm` to 3 statute miles, `weather_wind_max_kt` to
    25 knots, and `weather_validity_min` to 60 minutes."
    PRD §3.1: "The community-relations knobs default to
    `complaint_quota_threshold` of 3 substantiated complaints inside a
    `complaint_window_days` window of 30 days, and the reservations hold lives
    `hold_expire_minutes` minutes, defaulting to 30."
    PRD §3.1: "A new base starts with `posture` NORMAL — posture is always
    derived from weather observations, never set directly — and an
    `ops_run_index` of 0, incremented once per batch tick."

    Design: Corner/entities/base_creation_applies_defaults
    """
    set_clock("2026-08-03T00:00:00Z")
    data = validate_success(
        api.create_base(create_base_payload(), OPS), expected_status=201
    )
    assert_base(data)
    assert data["weather_ceiling_min_ft"] == 1000
    assert data["weather_visibility_min_sm"] == 3
    assert data["weather_wind_max_kt"] == 25
    assert data["weather_validity_min"] == 60
    assert data["complaint_quota_threshold"] == 3
    assert data["complaint_window_days"] == 30
    assert data["hold_expire_minutes"] == 30
    assert data["posture"] == "NORMAL"
    assert data["ops_run_index"] == 0


def test_route_creation_derives_turn_minutes(api):
    """PRD §3.1: "The turnaround buffer `turn_minutes` is derived from the
    tier — 15 minutes for SHORT, 25 for STANDARD, 40 for GRAND — and never
    supplied directly."
    PRD §3.1: "A route is created ACTIVE, and its
    `substantiated_complaints_30d` counter is recomputed from complaints on
    every read (§3.9)."

    Design: Corner/entities/route_creation_derives_turn_minutes
    """
    short = create_route(route_code="RS", tier="SHORT", duration_minutes=25)
    std = create_route(route_code="RT", tier="STANDARD", duration_minutes=50,
                       base_seat_price_cents=30000, fuel_required_lb=450)
    grand = create_route(route_code="RG", tier="GRAND", duration_minutes=75,
                         base_seat_price_cents=40000, fuel_required_lb=600)
    assert short["turn_minutes"] == 15
    assert std["turn_minutes"] == 25
    assert grand["turn_minutes"] == 40
    assert short["status"] == "ACTIVE"


def test_flight_creation_computes_derived_fields(api):
    """PRD §3.3: "Its `scheduled_arrival_utc` is the departure plus the
    route's `duration_minutes`; its `rotation_seq` is assigned per aircraft
    per UTC date by ordering that aircraft's non-cancelled flights by
    departure ascending and numbering from 1; `created_by_user_id` records
    the creating dispatcher's `X-User-ID`; `pilot_acknowledged` starts false;
    `actual_departure_utc`, `actual_arrival_utc`, and `cancel_reason` start
    null."
    PRD §3.3: "Three load figures track the flight's bookings: `seats_booked`
    sums `seat_count` over bookings in HELD, CONFIRMED, CHECKED_IN, or
    MANIFESTED; `seats_available` is the aircraft's `seat_capacity` minus
    `seats_booked`; and `estimated_gross_weight_lb` keeps the running
    provisional estimate of §3.5."

    Design: Corner/entities/flight_creation_computes_derived_fields
    """
    env = setup_ops_env()
    data = validate_success(
        api.create_flight(
            {
                "base_id": env["base"]["id"],
                "route_id": env["route"]["id"],
                "aircraft_id": env["aircraft"]["id"],
                "pilot_id": env["pilot"]["id"],
                "scheduled_departure_utc": "2026-08-03T14:00:00Z",
            },
            DISP,
        ),
        expected_status=201,
    )
    assert_flight(data)
    assert data["status"] == "SCHEDULED"
    assert_instant_equals(data["scheduled_arrival_utc"], "2026-08-03T14:25:00Z",
                          "scheduled_arrival_utc")
    assert data["rotation_seq"] == 1
    assert data["seats_booked"] == 0
    assert data["seats_available"] == 4
    # Provisional estimate: empty 1500 + no passengers + full fuel 300.
    assert data["estimated_gross_weight_lb"] == 1800
    assert data["pilot_acknowledged"] is False
    assert data["actual_departure_utc"] is None
    assert data["cancel_reason"] is None
    assert data["created_by_user_id"] == "disp-1"


def test_weather_observation_computed_fields_and_immutability(api):
    """PRD §2.4: "The single exception is `WeatherObservation`: observations
    are immutable once recorded and carry only `id` and `created_at` — both
    `updated_at` and `version` are absent from that resource."
    PRD §3.2: "`adverse` is true when the ceiling is below the base's
    `weather_ceiling_min_ft`, or visibility is below
    `weather_visibility_min_sm`, or wind exceeds `weather_wind_max_kt`.
    `validity_until` is `observed_at` plus the base's `weather_validity_min`
    minutes."
    PRD §3.2: "Posture is WEATHER_HOLD exactly when that observation exists,
    is adverse, and now is strictly before its `validity_until`; in every
    other case posture is NORMAL."

    Design: Corner/entities/weather_observation_computed_fields_and_immutability
    """
    set_clock("2026-08-03T12:00:00Z")
    base = create_base()
    data = validate_success(
        api.create_weather_observation(
            {
                "base_id": base["id"],
                "observed_at": "2026-08-03T11:00:00Z",
                "ceiling_ft": 5000,
                "visibility_sm": 10,
                "wind_kt": 26,
            },
            DISP,
        ),
        expected_status=201,
    )
    assert_weather_observation(data)
    # Wind 26 > weather_wind_max_kt 25 alone is sufficient for adverse.
    assert data["adverse"] is True
    assert_instant_equals(data["validity_until"], "2026-08-03T12:00:00Z",
                          "validity_until")
    # now == validity_until: strict-< fails, so posture is NORMAL.
    posture = get_base(base["id"])["posture"]
    assert posture == "NORMAL"


def test_missing_required_field_rejected_unknown_field_ignored(api):
    """PRD §2.9: "1. **Request validity** — the body parses, required fields
    are present, enum values are valid; unknown fields are ignored. Failure:
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/missing_required_field_rejected_unknown_field_ignored
    """
    payload = create_route_payload(route_code="R1")
    del payload["route_code"]
    resp = api.create_route(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    ok_payload = create_route_payload(route_code="R1")
    ok_payload["sponsor_name"] = "ACME"
    resp = api.create_route(ok_payload, OPS)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert data["route_code"] == "R1"
    assert "sponsor_name" not in data, "unknown input field must be ignored"


def test_invalid_enum_and_range_values_rejected(api):
    """PRD §2.9: "1. **Request validity** — the body parses, required fields
    are present, enum values are valid; unknown fields are ignored. Failure:
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "a `multiplier_bps` between 1 and 30000 basis points."
    PRD §3.1: "Creation rejects a window that overlaps any PUBLISHED season —
    adjacency, where one season's `end_date` equals another's `start_date`,
    is allowed — or whose end is not after its start, with
    `ERR_SEASON_OVERLAP`."

    Design: Corner/entities/invalid_enum_and_range_values_rejected
    """
    from test_helpers.factories import create_aircraft_payload, create_season_payload

    resp = api.create_aircraft(create_aircraft_payload(noise_class="ULTRA"), OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    resp = api.create_season(
        create_season_payload(label="BAD", multiplier_bps=40000), OPS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    resp = api.create_season(
        create_season_payload(label="DEGEN", start_date="2026-06-01",
                              end_date="2026-06-01", multiplier_bps=10000),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_SEASON_OVERLAP)


def test_get_nonexistent_resource_returns_not_found(api):
    """PRD §2.4: "Whenever a request addresses resources by identifier, path
    identifiers are validated first, left to right along the URL, followed by
    foreign-key identifiers in the body; the first unknown identifier is
    rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_resource_returns_not_found
    """
    missing = "00000000-0000-4000-8000-000000000000"
    validate_error(api.get_flight(missing, DISP), ApiErrorId.ERR_NOT_FOUND)
    validate_error(api.get_booking(missing, AGENT), ApiErrorId.ERR_NOT_FOUND)


def test_create_booking_with_unknown_flight_returns_not_found(api):
    """PRD §2.4: "Whenever a request addresses resources by identifier, path
    identifiers are validated first, left to right along the URL, followed by
    foreign-key identifiers in the body; the first unknown identifier is
    rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_booking_with_unknown_flight_returns_not_found
    """
    resp = api.create_booking(
        {
            "flight_id": "00000000-0000-4000-8000-000000000000",
            "contact_name": "A",
            "contact_email": "a@x.com",
            "passengers": [passenger_entry("P0", 150)],
        },
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_pilot_creation_mints_system_fields(api):
    """PRD §2.4: "Every persisted resource carries an `id` that is a
    server-minted UUID with no type prefix, a `created_at` timestamp, an
    `updated_at` timestamp, and an integer `version`."
    PRD §3.1: "Pilot registration records a `display_name` and a
    `certificate_no` unique across all pilots (again
    `ERR_UNIQUENESS_CONFLICT`); a pilot begins AVAILABLE."

    Design: Corner/entities/pilot_creation_mints_system_fields
    """
    set_clock("2026-08-03T00:00:00Z")
    data = validate_success(
        api.create_pilot(create_pilot_payload(display_name="Pat One",
                                              certificate_no="C1"), OPS),
        expected_status=201,
    )
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)
    assert data["status"] == "AVAILABLE"


def test_pilots_list_paginates_with_limit_offset(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit`
    (default 10, minimum 1, maximum 100) and `offset` (default 0). Responses
    place `limit`, `offset`, `total_count`, and `has_more` in `meta`."

    Design: Corner/entities/pilots_list_paginates_with_limit_offset
    """
    create_pilot(display_name="Pat One", certificate_no="C1")
    create_pilot(display_name="Pat Two", certificate_no="C2")
    create_pilot(display_name="Pat Three", certificate_no="C3")

    page1, meta1 = validate_paginated(
        api.list_pilots(DISP, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_pilots(DISP, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False
    assert page1[0]["certificate_no"] != page2[0]["certificate_no"]

    page_all, meta_all = validate_paginated(api.list_pilots(DISP))
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0
    assert len(page_all) == 3 and meta_all["has_more"] is False


def test_booking_creation_pins_waiver_and_computed_fields(api):
    """PRD §3.5: "A created booking lands in HELD with its quote locked,
    `expires_at` set to `created_at` plus the base's `hold_expire_minutes`,
    `waiver_version_pinned` captured from the base's
    `current_waiver_version`, and its `Passenger` rows created with
    `pax_index` assigned 0, 1, 2… in input order."
    PRD §3.5: "The money fields start clean: `paid_cents`,
    `refunded_card_cents`, `credited_cents`, `retained_fee_cents`, and
    `credits_applied_cents` all start at 0."
    PRD §3.5: "First comes the seasonal multiplier: the `multiplier_bps` of
    the PUBLISHED season whose window covers the departure date, ten thousand
    basis points when no PUBLISHED season covers it (RETIRED seasons are
    invisible to this selection), and the covering season's `id` is
    remembered on the booking as `season_id` — null in the fallback case."

    Design: Corner/entities/booking_creation_pins_waiver_and_computed_fields
    """
    env = setup_ops_env(base_overrides={"current_waiver_version": "WAV-9"})
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    data = validate_success(
        api.create_booking(
            {
                "flight_id": flight["id"],
                "contact_name": "A",
                "contact_email": "a@x.com",
                "passengers": [passenger_entry("P0", 150),
                               passenger_entry("P1", 160)],
            },
            AGENT,
        ),
        expected_status=201,
    )
    assert data["status"] == "HELD"
    assert data["paid_cents"] == 0
    assert data["seat_count"] == 2
    assert data["waiver_version_pinned"] == "WAV-9"
    # expires_at is created_at plus the base's 30-minute hold (default).
    delta = parse_instant(data["expires_at"]) - parse_instant(data["created_at"])
    assert delta.total_seconds() == 30 * 60
    # No PUBLISHED season covers 2026-08-03: parity season, load tier parity,
    # weekday -> 25000 per seat; season_id null in the fallback case.
    assert data["quoted_per_seat_cents"] == 25000
    assert data["quoted_total_cents"] == 50000
    assert data["season_id"] is None
