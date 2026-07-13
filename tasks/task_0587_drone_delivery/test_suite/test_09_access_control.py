"""Flight-crew identity: authentication, role authorization and order ownership."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    create_customer,
    create_incident,
    create_order_payload,
    create_service_area,
    dispatch_order_payload,
    read_incident,
    read_order,
    setup_quoted_order,
    setup_world,
)
from test_helpers.test_users import TEST_USERS, make_customer_headers

OPERATOR = TEST_USERS["dispatch_operator_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


def test_a_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they act. If either
    header is absent, or if `X-User-Role` is not one of the five recognized role names, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "1. Authentication of the headers (`ERR_UNAUTHENTICATED`)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.get_order(NON_EXISTENT_UUID, {"Content-Type": "application/json"})

    # Authentication runs first, so this is a 401 and not the 404 the unknown id would earn.
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_a_customer_may_not_dispatch_their_own_order(api):
    """PRD §2.1: "Once authentication succeeds, the acting role is matched against the set of
    roles authorized for the requested operation (§4); a role outside that set is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.4: "Dispatch is the busiest operation in the system. A `DispatchOperator` initiates
    it against a `QUOTED` order, naming the `nest_id` the sortie should fly out of and supplying
    `expected_order_version` (§2.9)."

    Design: Corner/rbac/customer_cannot_dispatch_an_order
    """
    w = setup_world()
    customer_headers = make_customer_headers(w["customer"]["id"])
    order = validate_success(
        api.create_order(
            create_order_payload(w["customer"]["id"], w["sa"]["id"]), customer_headers
        ),
        201,
    )

    resp = api.dispatch_order(
        order["id"],
        dispatch_order_payload(w["nest"]["id"], order["version"]),
        customer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    assert read_order(order["id"])["status"] == "QUOTED"
    _, meta = validate_paginated(
        api.list_flights(OPERATOR, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, "no Flight is created by a forbidden dispatch"


def test_a_customer_may_only_cancel_their_own_order(api):
    """PRD §2.1: "Concretely, a `Customer` may only place an order whose `customer_id` equals
    their own `X-User-ID`, and may only cancel an order whose `customer_id` equals their own
    `X-User-ID`; a mismatch on either operation yields `ERR_NOT_ORDER_OWNER` (HTTP 403)."
    PRD §3.3: "A `QUOTED` order may be cancelled by its owning `Customer` or by a
    `DispatchOperator`, moving `QUOTED → CANCELLED` and advancing the order's `version` by one."

    Design: Corner/rbac/customer_cannot_cancel_another_customers_order
    """
    sa = create_service_area()
    ann = create_customer(name="Ann", email="ann@x.com", dropoff_lat=37.05, dropoff_lon=-122.0)
    bob = create_customer(name="Bob", email="bob@x.com", dropoff_lat=37.04, dropoff_lon=-122.0)

    order = validate_success(
        api.create_order(
            create_order_payload(ann["id"], sa["id"]), make_customer_headers(ann["id"])
        ),
        201,
    )

    intruder = api.cancel_order(order["id"], make_customer_headers(bob["id"]))
    validate_error(intruder, ApiErrorId.ERR_NOT_ORDER_OWNER.value)
    assert read_order(order["id"])["status"] == "QUOTED"

    owner = validate_success(
        api.cancel_order(order["id"], make_customer_headers(ann["id"]))
    )
    assert owner["status"] == "CANCELLED"


def test_a_dispatch_operator_may_not_review_an_incident(api):
    """PRD §2.1: "Once authentication succeeds, the acting role is matched against the set of
    roles authorized for the requested operation (§4); a role outside that set is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.8: "A `MaintenanceTech` opens the review, moving the incident `OPEN → UNDER_REVIEW`
    and advancing its `version`; an incident that is not `OPEN` is rejected with
    `ERR_INCIDENT_NOT_OPEN` (HTTP 409)."

    Design: Corner/rbac/dispatch_operator_cannot_review_an_incident
    """
    w = setup_world(with_battery=False)
    incident = create_incident(w["drone"]["id"], severity="MINOR", category="LOST_LINK")

    resp = api.review_incident(incident["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    assert read_incident(incident["id"])["status"] == "OPEN"
