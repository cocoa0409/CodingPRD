"""RBAC and authentication: role exclusivity, Operator ownership, and the missing-auth
case (PRD §2.1).

Corner queue (B) instances (section: rbac):
  - fueltech_cannot_create_operator
  - opsdispatcher_cannot_dispatch_fuel
  - operator_cannot_act_on_other_operators_slot
  - missing_role_header_unauthenticated
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    create_operator,
    create_aircraft,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_revoked_slot,
    create_operator_payload,
    create_requested_fuel_order,
    make_operator_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_fueltech_cannot_create_operator():
    """PRD §2.1: "Each operation is restricted to a defined set of roles; an authenticated
    caller whose role is not authorized for the requested operation is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `BillingClerk` owns operator accounts, fuel contracts, invoicing, and
    billing adjustments."

    FuelTech calling POST /operators (a BillingClerk-owned operation) →
    ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/fueltech_cannot_create_operator
    """
    res = api.create_operator(create_operator_payload(legal_name="X", contact_email="x@x.test"), FUEL)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_opsdispatcher_cannot_dispatch_fuel():
    """PRD §2.1: "an authenticated caller whose role is not authorized for the requested
    operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `FuelTech` owns fuel logistics and into-plane reconciliation."

    OpsDispatcher calling POST /fuel-orders/{id}/dispatch (a FuelTech-only operation) →
    ERR_FORBIDDEN_ROLE (403); the order stays REQUESTED.

    Design: Corner/rbac/opsdispatcher_cannot_dispatch_fuel
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=False)
    res = api.dispatch_fuel_order(order["id"], OPS)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
    after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert after["logistics_status"] == "REQUESTED"


def test_operator_cannot_re_request_other_operators_slot():
    """PRD §2.1: "When an `Operator` caller targets a resource whose owning `operator_id`
    differs from `X-User-ID` — for example, re-requesting a revoked slot that belongs to
    another operator's visit — the request is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Operator A re-requesting a REVOKED slot owned by operator B → ERR_NOT_RESOURCE_OWNER
    (403); the slot stays REVOKED.

    Design: Corner/rbac/operator_cannot_act_on_other_operators_slot
    """
    operator_b = create_operator(legal_name="Op B", contact_email="b@aero.test")
    operator_a = create_operator(legal_name="Op A", contact_email="a@aero.test")
    aircraft_b = create_aircraft(operator_b["id"], tail_number="N1B", fuel_type="JET_A", mtow_lb=30000)
    _visit, _pad, slot = setup_revoked_slot(operator_b["id"], aircraft_b["id"],
                                            pad_overrides={"label": "PAD-77"})
    res = api.re_request_ramp_slot(slot["id"], make_operator_headers(operator_a["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
    after = get_success_data(api.get_ramp_slot(slot["id"], OPS))
    assert after["status"] == "REVOKED"


def test_missing_role_header_unauthenticated():
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    A request with no X-User-Role / X-User-ID headers → ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.create_operator(create_operator_payload(legal_name="X", contact_email="x@x.test"), {})
    validate_error(res, "ERR_UNAUTHENTICATED")
