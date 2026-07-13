"""Resource creation: field echo, system-minted fields, computed fields, defaults,
required-field and enum validation, and not-found reads.

Corner queue: entities section.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    new_depot,
)

YARD = TEST_USERS["yard_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]


def test_create_depot_snapshots_opening_inventory(api):
    """PRD §3.1: "A depot is registered with a human `name` and its opening inventory —
    `salt_tons_on_hand` and `brine_gallons_on_hand` — at which point the system snapshots
    those opening balances into `initial_salt_tons` and `initial_brine_gallons` as the
    permanent conservation anchor." PRD §2.4: "an integer `version` that starts at 1 on
    creation".

    Design: Corner/entities/create_depot_success
    """
    resp = api.create_depot({"name": "Yard", "salt_tons_on_hand": 42.5,
                             "brine_gallons_on_hand": 500}, YARD)
    data = validate_success(resp, 201)
    assert data["salt_tons_on_hand"] == 42.5, data
    assert data["initial_salt_tons"] == 42.5, data
    assert data["version"] == 1, data


def test_get_unknown_storm_returns_not_found(api):
    """PRD §2.10: "every path id and every body foreign key — storm, route, vehicle,
    operator, depot, assignment, callout, and application references — is resolved
    left-to-right along the URL hierarchy, and the first that fails to resolve yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/storm_not_found_returns_404
    """
    resp = api.get_storm_event(NON_EXISTENT_UUID, DISPATCH)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_operator_missing_rate_rejected(api):
    """PRD §2.10: "the request body is checked for well-formedness — required fields
    present, enum values within their declared sets, and numbers within their stated
    constraints — yielding `ERR_INVALID_REQUEST` (HTTP 400) for a malformed body". PRD
    §3.1: "An operator is registered with a `full_name`, a roster `badge_number`, a
    commercial license `cdl_class` (one of `A`, `B`, or `C`), and an `hourly_rate_cents`
    straight-time wage."

    Design: Corner/entities/operator_create_missing_required_field
    """
    resp = api.create_operator({"full_name": "No Rate", "badge_number": "B9",
                                "cdl_class": "B"}, YARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_route_invalid_tier_enum_rejected(api):
    """PRD §2.10: "or `ERR_INVALID_ENUM` (HTTP 422) specifically when an enum field
    carries a value outside its declared set." PRD §3.1: "The `tier` is either `ARTERIAL`
    — a primary corridor plowed and salted first — or `RESIDENTIAL`, a lower-priority
    street group".

    Design: Corner/entities/route_invalid_enum_returns_422
    """
    resp = api.create_route({"name": "Bad", "tier": "HIGHWAY", "lane_miles": 1.0,
                             "zone": "Z9"}, DISPATCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 422)


def test_vehicle_has_spreader_computed_from_type(api):
    """PRD §3.1: "From that type the system computes `has_spreader`, which is true exactly
    when the `vehicle_type` is `SPREADER` or `COMBO`; a vehicle needs a spreader to service
    a salting or brining run."

    Design: Corner/entities/vehicle_has_spreader_computed
    """
    depot = new_depot(salt_tons_on_hand=10, brine_gallons_on_hand=10)
    plow = validate_success(api.create_vehicle(
        {"home_depot_id": depot["id"], "unit_number": "P1", "vehicle_type": "PLOW"}, YARD), 201)
    combo = validate_success(api.create_vehicle(
        {"home_depot_id": depot["id"], "unit_number": "C1", "vehicle_type": "COMBO"}, YARD), 201)
    assert plow["has_spreader"] is False, plow
    assert combo["has_spreader"] is True, combo


def test_vehicle_defaults_status_available(api):
    """PRD §3.1: "A vehicle's `status` is one of `AVAILABLE` (idle), `ASSIGNED` (reserved
    to an in-progress run), or `OUT_OF_SERVICE` (in maintenance), and it defaults to
    `AVAILABLE` when not supplied at creation."

    Design: Corner/entities/vehicle_default_status_available
    """
    depot = new_depot(salt_tons_on_hand=10, brine_gallons_on_hand=10)
    veh = validate_success(api.create_vehicle(
        {"home_depot_id": depot["id"], "unit_number": "V1", "vehicle_type": "COMBO"}, YARD), 201)
    assert veh["status"] == "AVAILABLE", veh


def test_storm_system_fields_initialized(api):
    """PRD §3.2: "The operational axis, `operational_status`, begins at `PLANNED`".
    PRD §3.2: "The billing axis, `billing_status`, begins at `OPEN`". PRD §2.4: "an
    integer `version` that starts at 1 on creation".

    Design: Corner/entities/storm_system_fields_generated
    """
    resp = api.create_storm_event({"name": "S", "severity": "LIGHT",
                                   "forecast_start_at": "2026-02-10T00:00:00Z",
                                   "forecast_end_at": "2026-02-11T00:00:00Z"}, DISPATCH)
    data = validate_success(resp, 201)
    assert data["operational_status"] == "PLANNED", data
    assert data["billing_status"] == "OPEN", data
    assert data["version"] == 1, data
