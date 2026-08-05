"""Provisioning the depot estate, telemetry ingestion, and listing envelopes.

Corner (queue B) translations for entity creation, foreign-key integrity,
telemetry-driven readiness, reverse-reachable sub-resources, and pagination.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, fm_headers, op_headers,
)
import test_helpers.factories as fac
import test_helpers.fixtures as fx


def test_create_depot_returns_201_with_initialized_ledgers(api):
    """PRD §3.1: "Upon creation a depot's two ledgers, `reserved_load_kw` and
    `reimbursement_committed_cents`, are both initialized to 0 and its `version`
    to 1."

    Design: Corner/entities/create_depot_returns_201_with_fields
    """
    resp = api.create_depot(fac.create_depot_payload(name="D"), fm_headers())
    data = validate_success(resp, 201)
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert data["reserved_load_kw"] == 0, "reserved_load_kw must init to 0"
    assert data["reimbursement_committed_cents"] == 0, "reimbursement_committed_cents must init to 0"


def test_get_unknown_depot_returns_not_found(api):
    """PRD §2.5: "Each missing reference raises the not-found error specific to
    the referenced resource type — `ERR_DEPOT_NOT_FOUND`, `ERR_CHARGER_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or
    `ERR_INVOICE_NOT_FOUND` — each carrying HTTP 404."

    Design: Corner/entities/get_depot_nonexistent_returns_not_found
    """
    resp = api.get_depot(NON_EXISTENT_UUID, fm_headers())
    validate_error(resp, ApiErrorId.ERR_DEPOT_NOT_FOUND.value)


def test_create_charger_missing_connector_returns_validation(api):
    """PRD §2.10: "(4) structural validation of the body — required fields
    present, enum values legal, numeric ranges respected — yielding
    `ERR_VALIDATION`, or `ERR_ASSET_TARGET_INVALID` for a work order whose
    `asset_type` does not match the id field supplied".

    Design: Corner/entities/create_charger_missing_connector_returns_validation
    """
    depot = fx.new_depot(api)
    payload = {"depot_id": depot["id"], "name": "C1", "max_power_kw": 150}
    resp = api.create_charger(payload, fm_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_charger_unknown_depot_returns_not_found(api):
    """PRD §2.5: "Path identifiers are always validated before the request body;
    foreign-key references inside the body are validated after the path, in the
    order they are declared."
    PRD §2.5: "Each missing reference raises the not-found error specific to the
    referenced resource type — `ERR_DEPOT_NOT_FOUND`, `ERR_CHARGER_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or
    `ERR_INVOICE_NOT_FOUND` — each carrying HTTP 404."

    Design: Corner/entities/create_charger_unknown_depot_returns_not_found
    """
    payload = fac.create_charger_payload(NON_EXISTENT_UUID, name="C1")
    resp = api.create_charger(payload, fm_headers())
    validate_error(resp, ApiErrorId.ERR_DEPOT_NOT_FOUND.value)


def test_telemetry_overwrites_soc_and_flips_readiness_ready(api):
    """PRD §3.2: "the vehicle's `current_soc_pct` is set to the reading's
    `soc_pct` and its `odometer_km` is set to the reading's `odometer_km`."
    PRD §3.2: "a vehicle is `READY` when, and only when, its `status` is
    `IN_SERVICE` and its `current_soc_pct` is at least the minimum ready
    threshold of 80 percent (the `MIN_READY_SOC_PCT` constant); otherwise it is
    `NOT_READY`."

    Design: Corner/entities/telemetry_updates_soc_and_flips_readiness_ready
    """
    depot = fx.new_depot(api)
    vehicle = fx.new_vehicle(api, depot["id"], current_soc_pct=50)
    assert vehicle["readiness_status"] == "NOT_READY"

    validate_success(api.ingest_telemetry(vehicle["id"], {"soc_pct": 90, "odometer_km": 12000}, op_headers()), 201)

    after = get_success_data(api.get_vehicle(vehicle["id"], fm_headers()))
    assert after["current_soc_pct"] == 90, f"soc must overwrite to 90, got {after['current_soc_pct']}"
    assert after["odometer_km"] == 12000, f"odometer must overwrite to 12000, got {after['odometer_km']}"
    assert after["readiness_status"] == "READY", "90>=80 in service => READY"


def test_list_vehicle_telemetry_reverse_reachability(api):
    """PRD §3.2: "A telemetry reading is stored as an immutable event and
    returned with HTTP 201."
    PRD §2.3: "`total_count` reports the number of records matching the query
    before the page window is applied".

    Design: Corner/entities/list_telemetry_reverse_reachability
    """
    depot = fx.new_depot(api)
    vehicle = fx.new_vehicle(api, depot["id"], current_soc_pct=50)
    validate_success(api.ingest_telemetry(vehicle["id"], {"soc_pct": 60, "odometer_km": 100}, op_headers()), 201)

    data, meta = validate_paginated(api.list_telemetry(vehicle["id"], fm_headers()))
    assert meta["total_count"] == 1, f"expected 1 reading, got {meta['total_count']}"
    assert len(data) == 1
    assert data[0]["vehicle_id"] == vehicle["id"]


def test_list_chargers_pagination_envelope_and_filter(api):
    """PRD §2.3: "`total_count` reports the number of records matching the query
    before the page window is applied, and `has_more` is `true` exactly when
    records remain beyond the current page — that is, when the sum of `offset`
    and the number of returned records is less than `total_count`."

    Design: Corner/endpoints/list_chargers_pagination_envelope
    """
    depot = fx.new_depot(api)
    fx.new_charger(api, depot["id"], name="CA", connector_type="CCS", max_power_kw=150)
    fx.new_charger(api, depot["id"], name="CB", connector_type="NACS", max_power_kw=250)

    data, meta = validate_paginated(
        api.list_chargers(fm_headers(), params={"depot_id": depot["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "offset 0 + 1 returned < 2 => has_more true"
    assert len(data) == 1, "limit 1 returns exactly one item"


def test_depot_create_by_depot_operator_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/depot_create_by_depotoperator_returns_unauthorized
    """
    resp = api.create_depot(fac.create_depot_payload(name="D"), op_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name
    one of the five known roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.list_depots({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
