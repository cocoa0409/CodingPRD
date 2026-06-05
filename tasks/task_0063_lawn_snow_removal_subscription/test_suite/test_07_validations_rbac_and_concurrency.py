"""Breadth tests: validations, RBAC, OCC, dispatch fan-out, endpoints, consistency.

Covers queue B sections: validations, rbac, cross_cutting_complexity_layers,
endpoints, consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_unknown_role_headers,
    fixtures as fx,
)


# =====================================================================
# section: validations
# =====================================================================

def test_visit_property_mismatch_rejected(api):
    """PRD §2.7: "a service visit's contract and route stop must ultimately reference the same property. A request that violates this coherence is rejected with `ERR_PROPERTY_MISMATCH`."

    Contract on property A; stop on property B; the visit binding them is rejected.

    Design: Corner/validations/dispatch_property_mismatch_rejected
    """
    cust = fx.make_customer(service_zip="50001")
    propA = fx.make_property(cust["id"], zip="50001", address="Ra")
    propB = fx.make_property(cust["id"], zip="50001", address="Rb")
    conA = fx.make_contract(cust["id"], propA["id"], season="WINTER",
                            contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], conA["id"])
    route = fx.make_route(region_zip="50001")
    stopB = fx.make_route_stop(route["id"], propB["id"], base_service_minutes=30)
    resp = api.create_visit(
        {"contract_id": conA["id"], "route_stop_id": stopB["id"],
         "service_type": "LAWN", "runtime_hours": 1},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_MISMATCH.value, expected_status=409)


def test_skip_request_on_non_scheduled_visit_rejected(api):
    """PRD §3.7: "A skip request may only target a visit that is in `SCHEDULED` state; a request raised against a visit in any other state is rejected with `ERR_NO_SKIPPABLE_VISIT`."

    A DISPATCHED visit cannot be the target of a skip request.

    Design: Corner/validations/skip_request_on_non_scheduled_visit_rejected
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="50002",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
        with_crew=False,
    )
    resp = api.create_skip_request(
        {"visit_id": visit["id"], "reason": "late"},
        fx.make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SKIPPABLE_VISIT.value, expected_status=409)


def test_negative_runtime_hours_rejected(api):
    """PRD §3.6: "an optional `runtime_hours` (the equipment runtime the visit will consume, defaulting to zero and never negative) ... A visit created with a negative `snow_depth_in` or `runtime_hours` is rejected with `ERR_VALIDATION_RANGE`."

    Design: Corner/validations/negative_runtime_hours_rejected
    """
    ctx = fx.setup_route_with_stop(zip="50003",
                                   contract_overrides={"season": "SUMMER",
                                                       "contract_price_cents": 10000,
                                                       "term_months": 3})
    resp = api.create_visit(
        {"contract_id": ctx["contract"]["id"], "route_stop_id": ctx["stop"]["id"],
         "service_type": "LAWN", "runtime_hours": -1},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value, expected_status=422)


def test_missing_required_field_on_contract(api):
    """PRD §2.9: "Request well-formedness follows — required fields present and correctly
    typed, enum values legal, and numeric ranges honored (`ERR_INVALID_REQUEST`)."
    PRD §3.2: a contract is created with "a `contract_price_cents` flat seasonal base fee
    (which must be at least zero)."

    Omitting contract_price_cents yields ERR_INVALID_REQUEST.

    Design: Corner/validations/missing_required_field_on_contract
    """
    cust = fx.make_customer(service_zip="50004")
    prop = fx.make_property(cust["id"], zip="50004")
    resp = api.create_contract(
        {"customer_id": cust["id"], "property_id": prop["id"], "season": "WINTER",
         "term_months": 3},
        fx.make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


# =====================================================================
# section: rbac
# =====================================================================

def test_customer_cannot_approve_skip(api):
    """PRD §2.1: "When a request carries valid headers but the named role is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /skip-requests/{id}/approve is authorized for DispatchManager,
    PlatformAdmin only.

    A Customer calling approve is rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/customer_cannot_approve_skip
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="60001",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 30000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    resp = api.approve_skip_request(skip["id"], fx.make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_customer_cannot_access_other_customers_contract(api):
    """PRD §2.1: "When a `Customer` acts on a contract, property, preference, or skip request that does not resolve to their own `customer_id`, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Customer B reading Customer A's contract is rejected.

    Design: Corner/rbac/customer_cannot_access_other_customers_contract
    """
    custA = fx.make_customer(service_zip="60002")
    custB = fx.make_customer(service_zip="60003")
    propA = fx.make_property(custA["id"], zip="60002")
    conA = fx.make_contract(custA["id"], propA["id"], season="WINTER",
                            contract_price_cents=10000, term_months=3)
    resp = api.get_contract(conA["id"], fx.make_customer_headers(custB["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)


def test_unauthenticated_unknown_role_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    An unknown role on GET /customers/{id} is rejected with ERR_UNAUTHENTICATED.

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    cust = fx.make_customer(service_zip="60004")
    resp = api.get_customer(cust["id"], make_unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_crewlead_cannot_dispatch(api):
    """PRD §2.1: "the named role is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /visits/{id}/dispatch is authorized for DispatchManager, PlatformAdmin.

    A CrewLead calling dispatch is rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/crewlead_cannot_dispatch
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="60005",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
    )
    visit = fx.make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                          service_type="SNOW", snow_depth_in=3.0, runtime_hours=2)
    resp = api.dispatch_visit(visit["id"], fx.make_crew_headers(ctx["crew"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


# =====================================================================
# section: cross_cutting_complexity_layers
# =====================================================================

def test_equipment_rotate_correct_version_succeeds(api):
    """PRD §3.3: "On success the platform sets the new `assigned_route_id`, recomputes the equipment's `wear_score` (per Section 3.5), and increments the equipment's `version`."
    PRD §2.8: "A rotation request must carry `expected_equipment_version`, a non-optional field whose value is the `version` of the target `Equipment` as the client last observed it."

    Rotating with the current version (1) succeeds, sets assigned_route_id to route B,
    and bumps version to 2.

    Design: Corner/cross_cutting_complexity_layers/equipment_rotate_correct_version_succeeds
    """
    routeA = fx.make_route(region_zip="70001")
    routeB = fx.make_route(region_zip="70002")
    eq = fx.make_equipment(route_id=routeA["id"], equipment_type="PLOW", age_months=4)
    rotated = validate_success(
        api.rotate_equipment(eq["id"],
                             {"assigned_route_id": routeB["id"],
                              "expected_equipment_version": eq["version"]},
                             TEST_USERS["dispatcher_headers"])
    )
    assert rotated["assigned_route_id"] == routeB["id"]
    assert rotated["version"] == 2


def test_equipment_rotate_stale_version_conflict(api):
    """PRD §2.8: "Before applying the rotation, the platform compares
    `expected_equipment_version` against the equipment's current `version`. If they do
    not match ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    After one successful rotation (version -> 2), a second rotate carrying the stale
    version-1 token is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/equipment_rotate_stale_version_conflict
    """
    routeA = fx.make_route(region_zip="70003")
    routeB = fx.make_route(region_zip="70004")
    eq = fx.make_equipment(route_id=routeA["id"], equipment_type="PLOW", age_months=4)
    stale_version = eq["version"]
    fx.api_client.rotate_equipment(
        eq["id"], {"assigned_route_id": routeB["id"],
                   "expected_equipment_version": stale_version},
        TEST_USERS["dispatcher_headers"],
    )
    resp = api.rotate_equipment(
        eq["id"], {"assigned_route_id": routeA["id"],
                   "expected_equipment_version": stale_version},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_snow_dispatch_fanout_two_stops_two_visits(api):
    """PRD §3.4: "For every active route stop on the route whose property is not
    snow-opted-out, the platform creates a `SNOW` service visit and immediately advances
    it from `SCHEDULED` to `DISPATCHED` ... the route's `status` becomes `DISPATCHED`."

    Two active stops on two ACTIVE contracts: processing a >2.0 reading fans out one
    DISPATCHED SNOW visit per stop.

    Design: Corner/cross_cutting_complexity_layers/snow_dispatch_fanout_two_stops_two_visits
    """
    cust = fx.make_customer(service_zip="70005")
    prop1 = fx.make_property(cust["id"], zip="70005", address="Ta", lawn_area_sqft=1000)
    prop2 = fx.make_property(cust["id"], zip="70005", address="Tb", lawn_area_sqft=1000)
    con1 = fx.make_contract(cust["id"], prop1["id"], season="WINTER",
                            contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], con1["id"])
    con2 = fx.make_contract(cust["id"], prop2["id"], season="WINTER",
                            contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], con2["id"])
    route = fx.make_route(region_zip="70005", daily_capacity_minutes=480)
    fx.make_route_stop(route["id"], prop1["id"], sequence=1, base_service_minutes=30)
    fx.make_route_stop(route["id"], prop2["id"], sequence=2, base_service_minutes=30)
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=2,
                      asset_tag="EQ-CC3a-unique")
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=2,
                      asset_tag="EQ-CC3b-unique")
    wr = fx.make_weather_reading(region_zip="70005", snow_depth_in=3.0,
                                 observed_at="2026-01-16T06:00:00Z")
    api.process_weather_reading(wr["id"], {"route_id": route["id"]},
                                TEST_USERS["dispatcher_headers"])

    v1 = get_success_data(api.list_contract_visits(con1["id"], TEST_USERS["dispatcher_headers"]))
    v2 = get_success_data(api.list_contract_visits(con2["id"], TEST_USERS["dispatcher_headers"]))
    assert len(v1) == 1 and v1[0]["status"] == "DISPATCHED" and v1[0]["service_type"] == "SNOW"
    assert len(v2) == 1 and v2[0]["status"] == "DISPATCHED" and v2[0]["service_type"] == "SNOW"
    assert fx.get_route(route["id"])["status"] == "DISPATCHED"


def test_snow_just_above_two_dispatches(api):
    """PRD §3.4: "The platform will dispatch only when the reading's measured depth is
    strictly greater than 2.0 inches — a reading whose `snow_depth_in` is at or below 2.0
    produces no dispatch and is rejected with `ERR_SNOW_THRESHOLD_NOT_MET`."

    A reading at 2.1 crosses the threshold: route -> DISPATCHED and reading processed.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_snow_just_above_two_dispatches
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="70006",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
        with_crew=False,
    )
    wr = fx.make_weather_reading(region_zip="70006", snow_depth_in=2.1,
                                 observed_at="2026-01-17T06:00:00Z")
    result = validate_success(
        api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                    TEST_USERS["dispatcher_headers"])
    )
    assert result["status"] == "DISPATCHED"
    assert fx.get_weather_reading(wr["id"])["processed"] is True


# =====================================================================
# section: endpoints
# =====================================================================

def test_fk_reverse_route_stops_listing(api):
    """PRD §3.3: "a route's stops, homed crews, and assigned equipment can each be listed back through the route."
    PRD §4: GET /routes/{id}/stops — List RouteStops on a route.

    Design: Corner/endpoints/fk_reverse_route_stops_listing
    """
    cust = fx.make_customer(service_zip="80001")
    prop = fx.make_property(cust["id"], zip="80001")
    route = fx.make_route(region_zip="80001")
    stop = fx.make_route_stop(route["id"], prop["id"], base_service_minutes=30)
    stops = get_success_data(api.list_route_stops(route["id"], TEST_USERS["dispatcher_headers"]))
    assert len(stops) == 1
    assert any(s["id"] == stop["id"] for s in stops)


def test_fk_reverse_invoices_listing(api):
    """PRD §3.2: "The synthesized invoices for a contract can be listed back, as can the
    contract's service visits."
    PRD §3.9: the replay "begins from the contract's `contract_price_cents` as a running total" — with no visits and no skips the subtotal equals the base price.

    A CLOSED contract (price 10000, no visits/skips) has one invoice with subtotal 10000.

    Design: Corner/endpoints/fk_reverse_invoices_listing
    """
    _, _, con = fx.setup_active_contract(zip="80002",
                                         contract_overrides={"contract_price_cents": 10000,
                                                             "term_months": 3})
    fx.api_client.close_season(con["id"], TEST_USERS["dispatcher_headers"])
    invoices = get_success_data(
        api.list_contract_invoices(con["id"], TEST_USERS["dispatcher_headers"])
    )
    assert len(invoices) == 1
    assert invoices[0]["subtotal_cents"] == 10000


def test_cancel_scheduled_visit_succeeds(api):
    """PRD §3.6: "a `DispatchManager` may also cancel a `SCHEDULED` visit, moving it to `CANCELLED`."

    Design: Corner/endpoints/cancel_scheduled_visit_succeeds
    """
    ctx, visit = fx.setup_scheduled_visit(
        zip="80003",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 10000,
                            "term_months": 3},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
        with_equipment=False,
    )
    cancelled = validate_success(
        api.cancel_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    )
    assert cancelled["status"] == "CANCELLED"


# =====================================================================
# section: consistency_model
# =====================================================================

def test_wear_score_visible_immediately_after_completion(api):
    """PRD §2.6: "the server performs these secondary transitions automatically, without a separate client request against each affected resource."
    PRD §3.6: "recomputes its `wear_score` using the actual variant — that is, against
    the now-incremented counters."

    LAWN visit runtime 10 on equipment age 24: post-complete wear =
    round(2*10 + 5*1 + 0.5*24) = round(20 + 5 + 12) = 37, visible on the next GET.

    Design: Corner/consistency_model/immediate_visibility_of_wear_after_completion
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="90001",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 10000,
                            "term_months": 4},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 10},
        equipment_overrides={"equipment_type": "MOWER", "age_months": 24},
    )
    fx.complete(visit["id"], ctx["crew"]["id"])
    eq = get_success_data(api.get_equipment(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"]))
    assert eq["wear_score"] == 37, f"wear should be 37, got {eq['wear_score']}"
