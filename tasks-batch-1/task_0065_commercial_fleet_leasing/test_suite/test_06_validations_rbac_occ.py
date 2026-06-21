"""Corner tests (queue B): aggregation calcs, validation errors, list
pagination envelope, RBAC, and optimistic-concurrency. PRD §2.1, §2.3, §2.6,
§2.8, §3.4, §3.5, §3.7.
"""
from test_helpers import (
    TEST_USERS,
    create_allocation_payload,
    get_success_data,
    make_lessee_headers,
    read_lease,
    read_vehicle,
    setup_active_lease,
    setup_settlement_open,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["fleet_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


# ---- calculations ---------------------------------------------------------

def test_fuel_card_total_gallons_aggregation(api):
    """PRD §3.4: "Each successful post adds the transaction's gallons to the
    card's `total_gallons_purchased`."

    100 + 50 = 150 across two POSTED transactions.

    Design: Corner/calculations/fuel_card_total_gallons_aggregation_after_posts
    """
    _, _, lease = setup_active_lease(vehicle_class="HEAVY_DUTY")
    card = get_success_data(api.create_fuel_card(
        {"lease_id": lease["id"], "card_number": "CARD-AGG-1"}, FM))
    get_success_data(api.create_fuel_transaction(
        {"fuel_card_id": card["id"], "jurisdiction": "CA", "gallons": 100,
         "purchased_at": "2026-06-01T00:00:00Z"}, FM))
    get_success_data(api.create_fuel_transaction(
        {"fuel_card_id": card["id"], "jurisdiction": "NV", "gallons": 50,
         "purchased_at": "2026-06-02T00:00:00Z"}, FM))
    data = validate_success(api.get_fuel_card(card["id"], FM), 200)
    assert data["total_gallons_purchased"] == 150, data


def test_overage_zero_when_under_contracted_miles(api):
    """PRD §3.7: "take the lease's `odometer_end` minus its `odometer_start`
    minus its `contracted_miles`, and if that is negative treat it as zero."

    Driven to 50000 with contracted 60000 → excess_miles 0, charge 0.

    Design: Corner/calculations/overage_zero_when_under_contracted_miles
    """
    _, _, lease, settlement = setup_settlement_open(
        driven_odometer=50000, overage_model="CONTRACT_FLAT",
        contracted_miles=60000, per_mile_overage_cents=25,
        harsh_events=5, idle_minutes=20)
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert data["excess_miles"] == 0, data
    assert data["mileage_charge_cents"] == 0, data
    assert data["net_charge_cents"] == 0, data


# ---- validations ----------------------------------------------------------

def test_duplicate_vin_rejected(api):
    """PRD §2.8: "a vehicle's `vin` must be unique across all vehicles."

    A second vehicle with an already-used vin → ERR_DUPLICATE.

    Design: Corner/validations/duplicate_vin_returns_duplicate
    """
    get_success_data(api.create_vehicle({"vin": "VINDUP0001", "class": "LIGHT_DUTY"}, FM))
    resp = api.create_vehicle({"vin": "VINDUP0001", "class": "HEAVY_DUTY"}, FM)
    validate_error(resp, "ERR_DUPLICATE")


def test_odometer_regression_rejected(api):
    """PRD §3.5: "a reading whose odometer falls below the vehicle's current
    reading is rejected with `ERR_ODOMETER_REGRESSION` (HTTP 409)."

    A reading at 39000 after a prior reading advanced the vehicle to 40000.

    Design: Corner/validations/odometer_regression_returns_error
    """
    vehicle = get_success_data(api.create_vehicle(
        {"vin": "VINODO0001", "class": "HEAVY_DUTY"}, FM))
    get_success_data(api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "CA", "odometer_miles": 40000,
         "segment_miles": 40000, "recorded_at": "2026-05-01T00:00:00Z"}, TG))
    resp = api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "NV", "odometer_miles": 39000,
         "segment_miles": 100, "recorded_at": "2026-05-02T00:00:00Z"}, TG)
    validate_error(resp, "ERR_ODOMETER_REGRESSION")


def test_fuel_transaction_on_frozen_card_rejected(api):
    """PRD §3.4: "Posting a transaction is allowed only when the target card's
    `status` is `ACTIVE`; a transaction posted against a `FROZEN` or `CLOSED`
    card is rejected with `ERR_FUEL_CARD_NOT_ACTIVE` (HTTP 409)."

    The card is frozen by initiate-return, then a post is attempted.

    Design: Corner/validations/fuel_transaction_on_frozen_card_returns_error
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="HEAVY_DUTY")
    card = get_success_data(api.create_fuel_card(
        {"lease_id": lease["id"], "card_number": "CARD-FZ-1"}, FM))
    get_success_data(api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "CA", "odometer_miles": 70000,
         "segment_miles": 70000, "recorded_at": "2026-06-01T00:00:00Z"}, TG))
    get_success_data(api.initiate_return(lease["id"], FM))
    resp = api.create_fuel_transaction(
        {"fuel_card_id": card["id"], "jurisdiction": "CA", "gallons": 50,
         "purchased_at": "2026-06-02T00:00:00Z"}, FM)
    validate_error(resp, "ERR_FUEL_CARD_NOT_ACTIVE")


# ---- endpoints (list pagination envelope) ---------------------------------

def test_list_leases_filtered_pagination_envelope(api):
    """PRD §2.3: "For list responses, the `meta` object includes the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` is the total number of records matching the query across
    all pages and `has_more` indicates whether records remain beyond the
    current page."

    A lessee with two leases → total_count 2, has_more false.

    Design: Corner/endpoints/list_leases_filtered_by_lessee_pagination_envelope
    """
    lessee = get_success_data(api.create_lessee(
        {"company_name": "LP Co", "billing_email": "lp@x.com"}, FM))
    for vin, om, wf in [("VINLP00001", "CONTRACT_FLAT", "DEDUCTIBLE_FIRST"),
                        ("VINLP00002", "TIERED_EXCESS", "INSURANCE_FIRST")]:
        veh = get_success_data(api.create_vehicle({"vin": vin, "class": "LIGHT_DUTY"}, FM))
        get_success_data(api.create_lease(
            {"lessee_id": lessee["id"], "vehicle_id": veh["id"],
             "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
             "contracted_miles": 60000, "per_mile_overage_cents": 25,
             "overage_model": om, "collision_deductible_cents": 100000,
             "waterfall_model": wf}, FM))
    resp = api.list_leases(FM, params={"lessee_id": lessee["id"]})
    data, meta = validate_paginated(resp)
    assert meta.get("total_count") == 2, meta
    assert meta.get("has_more") is False, meta


# ---- rbac -----------------------------------------------------------------

def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller:
    `X-User-ID` and `X-User-Role`. If either header is missing, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other
    processing."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_vehicle({"vin": "VINAUTH001", "class": "LIGHT_DUTY"}, headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_lessee_cannot_create_vehicle_forbidden(api):
    """PRD §2.1: "If the headers are present but the named role is not
    permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /fleet/vehicles is authorized for FleetManager only.

    A Lessee calling it → ERR_FORBIDDEN.

    Design: Corner/rbac/lessee_cannot_create_vehicle_forbidden
    """
    lessee = get_success_data(api.create_lessee(
        {"company_name": "RB Co", "billing_email": "rb@x.com"}, FM))
    resp = api.create_vehicle(
        {"vin": "VINRBAC001", "class": "LIGHT_DUTY"},
        make_lessee_headers(lessee["id"]))
    validate_error(resp, "ERR_FORBIDDEN")


def test_fleetmanager_cannot_file_ifta_forbidden(api):
    """PRD §2.1: "If the headers are present but the named role is not
    permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /fleet/ifta-returns/{id}/file is authorized for
    ComplianceOfficer only.

    A FleetManager calling it → ERR_FORBIDDEN.

    Design: Corner/rbac/fleetmanager_cannot_file_ifta_forbidden
    """
    lessee = get_success_data(api.create_lessee(
        {"company_name": "RB2 Co", "billing_email": "rb2@x.com"}, FM))
    ifta = get_success_data(api.create_ifta_return(
        {"lessee_id": lessee["id"], "quarter": "2026Q1"}, CO))
    resp = api.file_ifta_return(ifta["id"], FM)
    validate_error(resp, "ERR_FORBIDDEN")


# ---- optimistic concurrency -----------------------------------------------

def test_occ_repair_create_stale_vehicle_version(api):
    """PRD §2.6: "Reporting a collision repair against a vehicle requires the
    request to include `expected_vehicle_version`, carrying the client's last
    observed `version` of that `Vehicle`. If that value does not match the
    vehicle's current `version` — because another writer has advanced the
    vehicle since the client last read it — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    The first repair create bumps the vehicle version; a second create with
    the now-stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_repair_create_stale_vehicle_version_conflict
    """
    _, vehicle, lease = setup_active_lease(vehicle_class="MEDIUM_DUTY")
    veh = read_vehicle(vehicle["id"])
    get_success_data(api.create_repair_order(
        {"vehicle_id": vehicle["id"], "lease_id": lease["id"],
         "expected_vehicle_version": veh["version"]}, FM))
    resp = api.create_repair_order(
        {"vehicle_id": vehicle["id"], "lease_id": lease["id"],
         "expected_vehicle_version": veh["version"]}, FM)
    validate_error(resp, "ERR_STALE_VERSION")


def test_occ_allocation_create_stale_lease_version(api):
    """PRD §2.6: "creating an allocation requires `expected_lease_version`,
    carrying the client's last observed `version` of the target `Lease`; if
    it does not match the lease's current `version`, the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    The first allocation create bumps the lease version; a second with the
    stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_allocation_create_stale_lease_version_conflict
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    d1 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "OD1", "license_number": "LIC-OCC2-1"}, FM))
    d2 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "OD2", "license_number": "LIC-OCC2-2"}, FM))
    get_success_data(api.create_allocation(
        create_allocation_payload(lease["id"], d1["id"], lease["version"]), FM))
    resp = api.create_allocation(
        create_allocation_payload(
            lease["id"], d2["id"], lease["version"],
            window_start="2026-07-01T00:00:00Z", window_end="2026-07-10T00:00:00Z"), FM)
    validate_error(resp, "ERR_STALE_VERSION")


def test_occ_allocation_create_current_version_succeeds(api):
    """PRD §3.3: "The create also carries `expected_lease_version` for the
    concurrency check described in §2.6; a stale value yields
    `ERR_STALE_VERSION` (HTTP 412). A successful create increments the lease's
    `version` by 1."

    A second allocation carrying the re-read current version succeeds (201)
    and the allocation is ASSIGNED.

    Design: Corner/cross_cutting_complexity_layers/occ_allocation_create_correct_lease_version_succeeds
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    d1 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "OD3a", "license_number": "LIC-OCC3-1"}, FM))
    d2 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "OD3b", "license_number": "LIC-OCC3-2"}, FM))
    get_success_data(api.create_allocation(
        create_allocation_payload(lease["id"], d1["id"], lease["version"]), FM))
    # The first create incremented the lease's version (PRD §3.3); re-read it.
    current_lease_version = read_lease(lease["id"])["version"]
    data = validate_success(api.create_allocation(
        create_allocation_payload(
            lease["id"], d2["id"], current_lease_version,
            window_start="2026-07-01T00:00:00Z", window_end="2026-07-10T00:00:00Z"), FM), 201)
    assert data["status"] == "ASSIGNED", data
