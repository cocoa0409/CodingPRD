"""Access control (PRD §2.1), optimistic concurrency (PRD §2.10), append-only
event records (PRD §2.4), CRUD validation and defaults (PRD §3.1-§3.3),
pagination (PRD §2.3), and list-filter reverse-reachability (PRD §3.10).

These translate Queue B corner instances in the entities / state_machines /
endpoints / errors / rbac / cross-cutting sections.
"""

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_round_trip_dispatched,
    create_equipment_class, create_location, create_customer, create_equipment,
    create_reservation, confirm_reservation,
    make_customer_headers, create_equipment_class_payload, create_location_payload,
    dispatch_payload, MISSING_UUID, TEST_USERS,
)

FM = TEST_USERS["fleet_manager_headers"]
LA = TEST_USERS["location_agent_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Optimistic concurrency (PRD §2.10)
# ─────────────────────────────────────────────────────────────────────────
def test_occ_stale_reservation_version_on_dispatch_412():
    """PRD §2.10: "Dispatching a reservation requires the request body to carry `expected_reservation_version`, which must equal the target reservation's current `version`."
    PRD §2.10: "If another writer has advanced the reservation's `version` since the agent last read it — for example, by already dispatching it, which legitimately consumes a unit and advances the fulfillment dimension — the agent's view is stale and the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_reservation_version_on_dispatch_412
    """
    s = setup_round_trip_dispatched(
        location_overrides={"name": "HUB", "lot_capacity": 5},
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    stale_version = s["reservation"]["version"]  # the pre-dispatch reservation version
    # Void so the reservation becomes dispatchable again, but its version has advanced.
    get_success_data(api_client.void_contract(s["contract"]["id"], FM))
    res = api_client.dispatch_reservation(
        s["reservation"]["id"], dispatch_payload(stale_version), LA
    )
    validate_error(res, "ERR_STALE_VERSION")


# ─────────────────────────────────────────────────────────────────────────
# Access control (PRD §2.1)
# ─────────────────────────────────────────────────────────────────────────
def test_customer_cannot_create_equipment_class_forbidden():
    """PRD §2.1: "When an authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_create_equipment_class_forbidden
    """
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    res = api_client.create_equipment_class(
        create_equipment_class_payload(code="TRUCK_X", category="TRUCK",
                                       daily_rate_cents=1000, mileage_rate_cents=50,
                                       one_way_flat_cents=5000, fuel_capacity_gallons=30),
        make_customer_headers(cust["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_location_agent_cannot_void_contract_forbidden():
    """PRD §2.1: "When an authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/location_agent_cannot_void_contract_forbidden
    """
    s = setup_round_trip_dispatched(
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    res = api_client.void_contract(s["contract"]["id"], LA)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_customer_cannot_confirm_other_customers_reservation_not_owner():
    """PRD §2.1: "when a `Customer` reads or acts upon a reservation or its downstream contract, the system requires that the reservation's `customer_id` equal `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_confirm_other_customers_reservation_not_owner
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    create_equipment(cls["id"], hub["id"])
    custa = create_customer(license_verified=True, loyalty_tier="STANDARD")
    custb = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(custa, cls["id"], hub["id"], hub["id"])
    res = api_client.confirm_reservation(resv["id"], make_customer_headers(custb["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "If either header is missing, or if the value of `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api_client.list_locations(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─────────────────────────────────────────────────────────────────────────
# Append-only event records (PRD §2.4)
# ─────────────────────────────────────────────────────────────────────────
def test_damage_report_immutable_no_version_field():
    """PRD §2.4: "a `DamageReport` and a `ChargeLedgerEntry` are append-only event records that are never modified after creation. Each of these carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/damage_report_immutable_no_version_field
    """
    s = setup_round_trip_dispatched(
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    res = api_client.file_damage_report(
        s["contract"]["id"], {"assessed_cost_cents": 5000, "description": "Scratch"}, LA
    )
    dr = validate_success(res, 201)
    assert "version" not in dr, "DamageReport must not carry a version field"
    assert "updated_at" not in dr, "DamageReport must not carry an updated_at field"
    listed = get_success_data(api_client.list_damage_reports(s["contract"]["id"], LA))
    assert any(r["id"] == dr["id"] for r in listed)


# ─────────────────────────────────────────────────────────────────────────
# CRUD: not-found, required fields, defaults, type constraints (PRD §3.1)
# ─────────────────────────────────────────────────────────────────────────
def test_get_equipment_class_not_found_returns_404():
    """PRD §2.5: "the first identifier in the path that does not name an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined."

    Design: Corner/entities/get_equipment_class_not_found_returns_404
    """
    res = api_client.get_equipment_class(MISSING_UUID, FM)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_location_missing_required_field_returns_invalid_request():
    """PRD §3.1: "A `RentalLocation` is created with a human-readable `name` (non-empty, between 1 and 120 characters), a `state_code` of exactly two uppercase letters that participates in one-way drop-off zoning, and a `lot_capacity` of at least 1."

    Design: Corner/entities/create_location_missing_required_field_returns_invalid_request
    """
    res = api_client.create_location({"name": "NoCap", "state_code": "CA"}, FM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_location_default_accepts_one_way_dropoff_true():
    """PRD §3.1: "The `accepts_one_way_dropoff` flag defaults to true and, when false, bars the location from being chosen as a one-way drop-off destination; the operational `status` defaults to `OPEN`. The computed `on_lot_count` starts at 0."

    Design: Corner/entities/create_location_default_accepts_one_way_dropoff_true
    """
    loc = validate_success(
        api_client.create_location(
            create_location_payload(name="Defaulted", state_code="CA", lot_capacity=3), FM
        ), 201,
    )
    assert loc["accepts_one_way_dropoff"] is True
    assert loc["status"] == "OPEN"
    assert loc["on_lot_count"] == 0


def test_create_equipment_class_invalid_category_enum_returns_invalid_request():
    """PRD §3.1: "Its `category` is one of `TRUCK`, `TRAILER`, or `TOW`, and this category drives the availability and mileage rules."

    Design: Corner/entities/create_equipment_class_invalid_category_enum_returns_invalid_request
    """
    res = api_client.create_equipment_class(
        create_equipment_class_payload(code="BOAT_30", category="BOAT",
                                       fuel_capacity_gallons=0), FM
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────
# State-machine invalid transitions (PRD §3.2, §3.6, §3.7)
# ─────────────────────────────────────────────────────────────────────────
def test_confirm_already_confirmed_returns_invalid_state():
    """PRD §3.6: "A `Customer` confirms their own `PENDING` reservation, advancing `booking_status` from `PENDING` to `CONFIRMED`."
    PRD §3.2: "Any transition attempted from the wrong state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_already_confirmed_returns_invalid_state
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    create_equipment(cls["id"], hub["id"])
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(cust, cls["id"], hub["id"], hub["id"])
    confirm_reservation(resv["id"], cust)
    res = api_client.confirm_reservation(resv["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_after_dispatch_returns_invalid_state():
    """PRD §3.6: "A `Customer` cancels their own reservation while it is `PENDING` or `CONFIRMED`, provided the fulfillment dimension is still `AWAITING_DISPATCH` — once a reservation has been dispatched it can no longer be cancelled."

    Design: Corner/state_machines/cancel_after_dispatch_returns_invalid_state
    """
    s = setup_round_trip_dispatched(
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    res = api_client.cancel_reservation(
        s["reservation"]["id"], make_customer_headers(s["customer"]["id"])
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_settle_before_return_active_contract_returns_invalid_state():
    """PRD §3.7: "A clean contract settles from `RETURNED_CLEAN` to `SETTLED`; a damaged contract settles from `RETURNED_DAMAGED` to `SETTLED`."

    Design: Corner/state_machines/settle_before_return_active_contract_returns_invalid_state
    """
    s = setup_round_trip_dispatched(
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    res = api_client.settle_contract(
        s["contract"]["id"], {"expected_contract_version": s["contract"]["version"]}, LA
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_maintenance_on_dispatched_unit_returns_invalid_state():
    """PRD §3.2: "A `FleetManager` may move a unit from `AVAILABLE` to `MAINTENANCE` and back".
    PRD §3.2: "Any transition attempted from the wrong state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/maintenance_on_dispatched_unit_returns_invalid_state
    """
    s = setup_round_trip_dispatched(
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    # Unit is off-lot (IN_TRANSIT) after dispatch.
    res = api_client.maintenance_equipment(s["eq"]["id"], FM)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────
# Pagination & list filters (PRD §2.3, §3.10)
# ─────────────────────────────────────────────────────────────────────────
def test_list_locations_pagination_envelope():
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_locations_pagination_envelope
    """
    create_location(name="L1", state_code="CA", lot_capacity=5)
    create_location(name="L2", state_code="NV", lot_capacity=5)
    data, meta = validate_paginated(api_client.list_locations(FM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_pagination_limit_out_of_bounds_returns_validation_pagination():
    """PRD §2.3: "A `limit` outside the range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/errors/pagination_limit_out_of_bounds_returns_validation_pagination
    """
    res = api_client.list_locations(FM, params={"limit": 101, "offset": 0})
    validate_error(res, "ERR_VALIDATION_PAGINATION")


def test_list_contracts_filtered_by_reservation():
    """PRD §3.10: "List endpoints throughout the system provide reverse reachability for the foreign keys that are otherwise only carried in bodies: reservations may be filtered by `customer_id`, `pickup_location_id`, `dropoff_location_id`, `equipment_class_id`, `coverage_plan_id`, `assigned_equipment_id`, `booking_status`, and `fulfillment_status`; equipment may be filtered by `equipment_class_id`, `current_location_id`, `home_location_id`, and `status`; contracts by `reservation_id`, `equipment_id`, and `status`".

    Design: Corner/endpoints/list_contracts_filtered_by_reservation
    """
    s = setup_round_trip_dispatched(
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    data, meta = validate_paginated(
        api_client.list_contracts(LA, params={"reservation_id": s["reservation"]["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == s["contract"]["id"]
