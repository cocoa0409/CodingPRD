"""Onboarding, creation defaults, and strict-schema claims (entities)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_client_payload, create_site_payload, create_contract_payload,
    create_storm_event_payload, create_observation_payload,
    setup_client, setup_storm_event, set_clock,
    assert_client, assert_observation,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]


def test_client_creation_defaults_and_default_clock(api):
    """PRD §2.4: "Before any call is made, the clock reads exactly `2026-05-01T00:00:00Z` as a fixed startup default."
    PRD §3.1: "The client's `credit_exposure_cents` starts at zero"
    PRD §2.5: "a `version` integer that starts at 1"

    Design: Corner/entities/client_creation_defaults_and_default_clock
    """
    resp = api.create_client(
        create_client_payload(name="Default Tester", credit_limit_cents=500000),
        DISPATCH)
    client = validate_success(resp, 201)
    assert_client(client)
    assert client["version"] == 1
    assert client["credit_exposure_cents"] == 0
    assert client["created_at"] == "2026-05-01T00:00:00.000Z", (
        "with the logical clock never set, created_at must be the fixed startup default")

    fetched = validate_success(api.get_client(client["id"], DISPATCH), 200)
    assert fetched["name"] == "Default Tester"


def test_site_missing_pavement_area_rejected(api):
    """PRD §2.8: "Ninth, schema sanity: required fields for the contract type, enum membership, well-formed windows with end after start, and rejection of unknown fields, all failing as `ERR_INVALID_REQUEST`."
    PRD §3.1: "A site is created with its owning `client_id`, a display `name`, a street `address`, a `region_code` that must match a storm event's `region_code` for the event to cover the site, a `pavement_area_sqft` plowable area that drives the area-normative material cap at true-up, and a `requires_loader` flag"

    Design: Corner/entities/site_missing_required_field_returns_invalid_request
    """
    client = setup_client(name="Req Fields Co", credit_limit_cents=500000)
    payload = {
        "client_id": client["id"],
        "name": "No Area Lot",
        "address": "1 Void St",
        "region_code": "NE",
    }
    validate_error(api.create_site(payload, DISPATCH), ApiErrorId.ERR_INVALID_REQUEST)


def test_per_push_contract_missing_rate_rejected(api):
    """PRD §3.1: "a `PER_PUSH` contract must carry `per_push_rate_cents`"
    PRD §3.1: "A creation that omits a type-required field fails schema sanity with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/contract_type_conditional_required_fields
    """
    client = setup_client(name="Conditional Co", credit_limit_cents=500000)
    payload = {
        "client_id": client["id"],
        "contract_type": "PER_PUSH",
        "season_start": "2026-11-01T00:00:00Z",
        "season_end": "2027-03-31T23:59:59Z",
    }
    validate_error(api.create_contract(payload, DISPATCH), ApiErrorId.ERR_INVALID_REQUEST)


def test_seasonal_contract_missing_cap_and_overage_rejected(api):
    """PRD §3.1: "a `SEASONAL` contract must carry `seasonal_fee_cents`, `seasonal_push_cap`, and `seasonal_overage_rate_cents`"
    PRD §3.1: "A creation that omits a type-required field fails schema sanity with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/contract_type_conditional_required_fields
    """
    client = setup_client(name="Conditional Co 2", credit_limit_cents=500000)
    payload = {
        "client_id": client["id"],
        "contract_type": "SEASONAL",
        "season_start": "2026-11-01T00:00:00Z",
        "season_end": "2027-03-31T23:59:59Z",
        "seasonal_fee_cents": 1_000_000,
    }
    validate_error(api.create_contract(payload, DISPATCH), ApiErrorId.ERR_INVALID_REQUEST)


def test_contract_invalid_enum_rejected(api):
    """PRD §3.1: "Contracts come in three kinds, selected by `contract_type`: `PER_PUSH`, `SEASONAL`, or `HOURLY`."
    PRD §2.8: "Ninth, schema sanity: required fields for the contract type, enum membership, well-formed windows with end after start, and rejection of unknown fields, all failing as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/contract_invalid_enum_returns_invalid_request
    """
    client = setup_client(name="Enum Co", credit_limit_cents=500000)
    payload = {
        "client_id": client["id"],
        "contract_type": "DAILY",
        "season_start": "2026-11-01T00:00:00Z",
        "season_end": "2027-03-31T23:59:59Z",
    }
    validate_error(api.create_contract(payload, DISPATCH), ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_contract_returns_not_found(api):
    """PRD §2.10: "the first identifier that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is evaluated."

    Design: Corner/entities/get_nonexistent_contract_returns_not_found
    """
    validate_error(api.get_contract(NON_EXISTENT_UUID, DISPATCH),
                   ApiErrorId.ERR_NOT_FOUND)


def test_weather_observation_append_only_immutable(api):
    """PRD §2.5: "The WeatherObservation feed record is the sole exception: it is immutable and append-only, and carries only `id` and `created_at` — `updated_at` and `version` are absent from it entirely."
    PRD §2.4: "All server-stamped timestamps — `created_at`, `updated_at`, `verified_at`, `challenged_at`, `closed_at`, `actual_start_at`, `completed_at`, `issued_at`, `settled_at`, and every other system-written instant — are read from a single logical clock, never from wall-clock time."

    Design: Corner/entities/weather_observation_append_only_immutable
    """
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    resp = api.create_observation(
        create_observation_payload(event["id"], "NOAA", "2026-12-10T07:30:00Z", 2.1),
        TEST_USERS["platform_admin_headers"])
    observation = validate_success(resp, 201)
    assert_observation(observation)
    assert observation["created_at"] == "2026-12-10T07:00:00.000Z"


def test_contract_computed_field_input_rejected(api):
    """PRD §2.8: "Ninth, schema sanity: required fields for the contract type, enum membership, well-formed windows with end after start, and rejection of unknown fields, all failing as `ERR_INVALID_REQUEST`."
    PRD §3.1: "`season_billed_cents` sums `total_cents` over the contract's invoices" — it is a derived accumulator, not a creation input (PRD §3.7).

    Design: Corner/entities/contract_computed_field_input_returns_invalid_request
    """
    client = setup_client(name="Strict Schema Co", credit_limit_cents=500000)
    payload = create_contract_payload(
        client["id"], contract_type="PER_PUSH",
        per_push_rate_cents=45_000, trigger_depth_inches=1.0,
    )
    payload["season_billed_cents"] = 999
    validate_error(api.create_contract(payload, DISPATCH), ApiErrorId.ERR_INVALID_REQUEST)


def test_contract_defaults_applied_on_create(api):
    """PRD §3.1: "`trigger_depth_inches` defaults to 2.00 inches (verified accumulation of at least this depth makes pushes billable), `hourly_tier_threshold_minutes` defaults to 2,400 minutes — forty hours of cumulative season billable time billed at tier 1 before tier 2 pricing takes over — `night_premium_pct` defaults to 0.25, `sla_miss_penalty_cents` defaults to 15000, `require_photo_verification` defaults to true, and the three material rate fields `salt_rate_per_lb_cents`, `blend_rate_per_lb_cents`, and `brine_rate_per_lb_cents` default to 25, 60, and 35 cents per pound respectively."

    Design: Corner/entities/contract_defaults_applied_on_create
    """
    client = setup_client(name="Defaults Co", credit_limit_cents=500000)
    payload = {
        "client_id": client["id"],
        "contract_type": "PER_PUSH",
        "season_start": "2026-11-01T00:00:00Z",
        "season_end": "2027-03-31T23:59:59Z",
        "per_push_rate_cents": 45_000,
    }
    contract = validate_success(api.create_contract(payload, DISPATCH), 201)
    assert contract["trigger_depth_inches"] == 2.0
    assert contract["sla_miss_penalty_cents"] == 15000
    assert contract["require_photo_verification"] is True
    assert contract["night_premium_pct"] == 0.25
    assert contract["hourly_tier_threshold_minutes"] == 2400
    assert contract["salt_rate_per_lb_cents"] == 25
    assert contract["blend_rate_per_lb_cents"] == 60
    assert contract["brine_rate_per_lb_cents"] == 35
