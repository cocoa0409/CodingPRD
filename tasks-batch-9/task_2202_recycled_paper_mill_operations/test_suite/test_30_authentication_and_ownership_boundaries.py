"""The four gates ahead of every business rule: headers present, role declared, an
entity-backed identity that resolves, and the row actually belonging to the caller.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, build_user_headers, make_customer_headers, make_supplier_headers,
    declare_fiber_grade, declare_tl_140, publish_quote, register_supplier,
    register_customer, create_draft_po, create_customer_order_payload,
    submit_order, po_version, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]

JSON = {"Content-Type": "application/json"}


def test_missing_headers_are_reported_ahead_of_an_undeclared_role_name():
    """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that principal is
    acting in. If either header is absent or present but empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If `X-User-Role` carries a value that is not one
    of the eight roles declared below, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP
    401)."
    PRD §2.8: "The global ordering is: authentication and role checks first (missing
    headers, unknown role, unresolvable entity-backed identity, role not permitted, resource
    ownership), then path existence resolved left to right, then pagination and request-shape
    validation, then body-reference resolution, then optimistic-concurrency version checks,
    then state-machine from-state checks, then segregation-of-duties checks, then the
    domain's business rules — safety and environmental gates, then constraint and capacity
    gates, then temporal gates, then the fiscal and ledger gates."

    Design: Corner/rbac/absent_headers_outrank_an_unknown_role_name
    """
    no_identity = dict(JSON, **{"X-User-Role": "MillSuperintendent"})
    empty_identity = dict(JSON, **{"X-User-ID": "", "X-User-Role": "FiberBuyer"})
    no_role = dict(JSON, **{"X-User-ID": "fb_1"})

    for headers in (no_identity, empty_identity, no_role):
        response = api_client.list_fiber_grades(headers)
        validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401)

    healthy = api_client.list_fiber_grades(BUYER)
    assert healthy.json()["meta"]["total_count"] == 0, \
        "the endpoint itself answers a properly identified caller"


def test_a_role_name_outside_the_declared_eight_never_reaches_the_row():
    """PRD §2.1: "If `X-User-Role` carries a value that is not one of the eight roles
    declared below, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."
    PRD §2.1: "The eight roles are `MillPlanner`, `FiberBuyer`, `QualityLab`,
    `MachineOperator`, `EnvironmentalOfficer`, `EnergyManager`, `Supplier`, and `Customer`."
    PRD §2.1: "Ownership and role checks are evaluated before any business-state reasoning:
    an unauthorised caller must not be able to learn a resource's state from the error it
    receives."

    Design: Corner/rbac/an_undeclared_role_is_rejected_before_identity_resolution
    """
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)

    for role in ("MillSuperintendent", "millplanner"):
        response = api_client.get_supplier(
            supplier["id"], build_user_headers(supplier["id"], role))
        validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)
        assert response.json()["response_type"] == "error"

    own_read = get_success_data(api_client.get_supplier(
        supplier["id"], make_supplier_headers(supplier["id"])))
    assert own_read["name"] == "Delta Fiber Recovery", \
        "the declared role reaches the same row the undeclared one could not"


def test_a_supplier_principal_carrying_a_customer_id_is_not_authenticated():
    """PRD §2.1: "When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting
    `Supplier` row; ownership checks on any resource that references a supplier compare that
    resource's `supplier_id` to `X-User-ID`."
    PRD §2.1: "For both of these roles, an `X-User-ID` that does not resolve to an existing
    row of the backing entity is rejected with `ERR_IDENTITY_NOT_FOUND` (HTTP 401)."
    PRD §3.1: "Confirmation is the supplier's move and the only write a `Supplier` principal
    may make."

    Design: Corner/rbac/an_entity_backed_role_whose_id_names_the_wrong_table_is_unauthenticated
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    customer = register_customer(name="Gulf Coast Box Co",
                                 allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    draft = create_draft_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                            negotiated_delta_per_ton=5.00)
    priced = validate_success(api_client.price_purchase_order(
        draft["id"], {"expected_purchase_order_version": draft["version"]}, BUYER))
    wrong_table = make_supplier_headers(customer["id"])

    validate_error(api_client.confirm_purchase_order(draft["id"], wrong_table),
                   ApiErrorId.ERR_IDENTITY_NOT_FOUND.value, 401)
    validate_error(api_client.get_purchase_order(draft["id"], wrong_table),
                   ApiErrorId.ERR_IDENTITY_NOT_FOUND.value, 401)

    unconfirmed = get_success_data(api_client.get_purchase_order(draft["id"], BUYER))
    assert unconfirmed["status"] == "PRICED", \
        "an unauthenticated principal cannot advance the order"
    assert unconfirmed["version"] == priced["version"]

    confirmed = validate_success(api_client.confirm_purchase_order(
        draft["id"], make_supplier_headers(supplier["id"])))
    assert confirmed["status"] == "CONFIRMED"


def test_one_customer_can_neither_read_nor_cancel_another_customers_order():
    """PRD §2.1: "A `Supplier` that acts on a purchase order it does not own, or a
    `Customer` that acts on another customer's order or profile, is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "Supplier reads of purchase orders and fiber receipts are restricted to rows
    whose `supplier_id` equals `X-User-ID`; customer reads of orders and profiles are
    restricted to rows whose `customer_id` equals `X-User-ID`."
    PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    `Customer` row; ownership checks on any resource that references a customer compare that
    resource's `customer_id` to `X-User-ID`."

    Design: Corner/rbac/one_customer_cannot_read_or_cancel_another_customers_order
    """
    declare_tl_140()
    first = register_customer(name="Gulf Coast Box Co", allocation_priority_tier="P2",
                              max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                              wrap_spec="KRAFT_ONLY")
    second = register_customer(name="Piedmont Tissue LLC",
                               allocation_priority_tier="P3",
                               max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                               wrap_spec="KRAFT_ONLY")
    order = submit_order(first, "TL_140", ordered_tons=10.00, roll_width_mm=2400,
                         roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY")
    intruder = make_customer_headers(second["id"])

    validate_error(api_client.get_customer(first["id"], intruder),
                   ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    validate_error(api_client.cancel_customer_order(order["id"], intruder),
                   ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    validate_error(api_client.create_customer_order(
        create_customer_order_payload(first["id"], "TL_140"), intruder),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    intruder_sees = api_client.list_customer_orders(intruder).json()
    assert intruder_sees["meta"]["total_count"] == 0
    assert intruder_sees["data"] == []
    owner_sees = api_client.list_customer_orders(
        make_customer_headers(first["id"])).json()
    assert owner_sees["meta"]["total_count"] == 1
    assert owner_sees["data"][0]["status"] == "SUBMITTED", \
        "the outsider's cancellation never landed"
