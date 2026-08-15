"""Season, driver and kart fundamentals: declared defaults, initial states,
the shared error envelope, authentication, pagination, the driver status cycle
and a role boundary on season creation."""
from test_helpers import (
    ApiErrorId,
    add_kart,
    assert_driver,
    assert_kart,
    assert_season,
    create_driver_payload,
    create_season_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_driver_headers,
    register_active_driver,
    register_driver,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_season_creation_applies_declared_defaults(api, league_admin_headers):
    """PRD 3.1: "A new season's `status` is `SCHEDULED`, and its derived counters
    `rounds_completed` and `collected_fees_cents` read zero until events complete
    and fees are paid."
    PRD 3.1: "A `LeagueAdmin` opens a championship by creating a season with a display
    `name`, a competition `year`, the `drop_rounds` count governing how many of each
    driver's lowest-scoring rounds are discarded in the final standings (a non-negative
    integer, defaulting to 0), the `points_scheme`, and optionally
    `fastest_lap_bonus_points` (an integer, defaulting to 0)."

    Design: Corner/entities/season_creation_defaults
    """
    # drop_rounds and fastest_lap_bonus_points deliberately omitted.
    response = api.create_season(
        {"name": "Defaults Cup", "year": 2026, "points_scheme": [25, 22, 20]},
        league_admin_headers,
    )
    season = validate_success(response, 201)
    assert_season(season)
    assert season["status"] == "SCHEDULED"
    assert season["drop_rounds"] == 0, "omitted drop_rounds must default to 0"
    assert season["fastest_lap_bonus_points"] == 0, (
        "omitted fastest_lap_bonus_points must default to 0"
    )
    assert season["rounds_completed"] == 0
    assert season["collected_fees_cents"] == 0
    assert isinstance(season["version"], int)
    assert is_valid_uuid(season["id"])

    fetched = validate_success(api.get_season(season["id"], league_admin_headers), 200)
    assert_season(fetched)
    assert fetched["status"] == "SCHEDULED"
    assert fetched["rounds_completed"] == 0
    assert fetched["collected_fees_cents"] == 0


def test_driver_registration_starts_pending_with_system_fields(api, league_admin_headers):
    """PRD 3.2: "New drivers start `PENDING`."
    PRD 2.4: "`id` (string): a server-minted UUID with no type prefix, unique across
    the system."
    PRD 2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
    digits, set at creation and never changed."

    Design: Corner/entities/driver_system_fields_and_initial_state
    """
    response = api.create_driver(
        create_driver_payload(
            full_name="Rookie",
            date_of_birth="2000-05-05",
            body_weight_kg=75.0,
            license_type="RENTAL",
        ),
        league_admin_headers,
    )
    driver = validate_success(response, 201)
    assert_driver(driver)
    assert driver["status"] == "PENDING", "a newly registered driver starts PENDING"
    assert isinstance(driver["version"], int)
    assert is_iso8601_timestamp(driver["created_at"])

    fetched = validate_success(api.get_driver(driver["id"], league_admin_headers), 200)
    assert_driver(fetched)
    assert fetched["status"] == "PENDING"


def test_get_unknown_driver_returns_not_found(api, league_admin_headers):
    """PRD 2.7: "The server resolves each path identifier — `season_id`, `class_id`,
    `event_id`, `entry_id`, `session_id`, `incident_id`, `driver_id`, `kart_id`,
    `booking_id` — in path order and rejects the request with `ERR_NOT_FOUND` (404) at
    the first identifier that does not correspond to an existing resource, without
    examining later segments."

    Design: Corner/entities/driver_get_not_found_returns_404
    """
    response = api.get_driver(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", league_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_error_envelope_shape_on_not_found(api, league_admin_headers):
    """PRD 2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    response = api.get_incident(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", league_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"]
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["meta"]["api_request_timestamp"]
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip()


def test_request_without_auth_headers_rejected(api):
    """PRD 2.1: "A request missing either header, or carrying a role outside this set,
    is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    response = api.list_karts(headers={})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_karts_list_pagination_and_status_filter(api, league_admin_headers):
    """PRD 2.3: "List endpoints accept the `limit` and `offset` query parameters."
    PRD 2.3: "Unless otherwise specified, list responses are sorted by `created_at` in
    ascending order."
    PRD 2.3: "The `meta` object of list responses carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD 4: "| GET | `/karting/karts` | List karts; optional `status` filter; paginated | Any |"

    Design: Corner/endpoints/karts_list_pagination_and_status_filter
    """
    k1 = add_kart(fleet_number="P-1")
    k2 = add_kart(fleet_number="P-2")
    k3 = add_kart(fleet_number="P-3")
    validate_success(
        api.update_kart(k3["id"], {"status": "IN_MAINTENANCE"}, league_admin_headers), 200
    )

    first_page, meta = validate_paginated(
        api.list_karts(league_admin_headers, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert [k["id"] for k in first_page] == [k1["id"], k2["id"]], (
        "created_at ascending order expected"
    )
    for kart in first_page:
        assert_kart(kart)

    filtered, filtered_meta = validate_paginated(
        api.list_karts(league_admin_headers, params={"status": "IN_MAINTENANCE"})
    )
    assert filtered_meta["total_count"] == 1
    assert len(filtered) == 1
    assert filtered[0]["id"] == k3["id"]
    assert filtered[0]["status"] == "IN_MAINTENANCE"


def test_driver_suspend_reinstate_cycle(api, league_admin_headers):
    """PRD 3.2: "A `LeagueAdmin` promotes a driver `PENDING → ACTIVE`, may suspend with
    `ACTIVE → SUSPENDED`, and may reinstate with `SUSPENDED → ACTIVE`; each change
    advances the driver's `version`."

    Design: Corner/state_machines/driver_suspend_reinstate_cycle
    """
    driver = register_driver(full_name="Cyc")
    activated = validate_success(
        api.update_driver(driver["id"], {"status": "ACTIVE"}, league_admin_headers), 200
    )
    assert activated["status"] == "ACTIVE"

    suspended = validate_success(
        api.update_driver(driver["id"], {"status": "SUSPENDED"}, league_admin_headers), 200
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == activated["version"] + 1

    reinstated = validate_success(
        api.update_driver(driver["id"], {"status": "ACTIVE"}, league_admin_headers), 200
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == activated["version"] + 2


def test_driver_cannot_create_season(api, league_admin_headers):
    """PRD 2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN` (403)."
    PRD 4: "| POST | `/karting/seasons` | Create a season (starts `SCHEDULED`, counters zero) | LeagueAdmin |"

    Design: Corner/rbac/driver_cannot_create_season
    """
    driver = register_active_driver(full_name="Wannabe Organizer")
    response = api.create_season(
        create_season_payload(name="Forbidden Cup"),
        make_driver_headers(driver["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN.value, 403)
