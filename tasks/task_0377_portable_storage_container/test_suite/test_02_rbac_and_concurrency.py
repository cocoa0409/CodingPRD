"""RBAC and optimistic-concurrency tests (PRD §2.1, §2.4, §2.7)."""
from test_helpers import (
    validate_success, validate_error,
    create_rental_agreement_payload, create_container_model_payload,
    reserve_payload, payment_payload,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

PA = TEST_USERS["platform_admin_headers"]
DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def test_customer_cannot_reserve(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the target
    endpoint — or which violates the ownership rule below — is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §4 endpoint table: "POST `/rental-agreements/{id}/reserve` | Reserve a
    container from inventory | DispatchOperator".

    Design: Corner/rbac/customer_cannot_reserve_returns_forbidden
    """
    F.create_container_model(size_code="C16")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="cf@x.com")
    cust_headers = make_customer_headers(cust["id"])

    ag = validate_success(api.create_rental_agreement(
        create_rental_agreement_payload(cust["id"], depot["id"], size_code="C16"),
        cust_headers), 201)
    res = api.reserve_agreement(ag["id"], reserve_payload(ag["version"]), cust_headers)
    validate_error(res, "ERR_FORBIDDEN")


def test_customer_cannot_hold_other_customers_agreement(api):
    """PRD §2.1: "a `Customer` may act only on rental agreements whose `customer_id` equals
    their `X-User-ID`, and on the sub-resources ... of those agreements; acting on another
    customer's agreement is an `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_hold_other_customers_agreement_forbidden
    """
    world = F.seed_world(size_code="C16", with_crew=True, customer_email="ca@x.com")
    cust_b = F.create_customer(email="cb@x.com")
    ag, _unit = F.deliver_and_activate(world)

    res = api.hold_agreement(ag["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role`, carries a role outside this set, or
    omits `X-User-ID` where an entity-backed role requires it, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.create_container_model(create_container_model_payload(size_code="C16"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_occ_reserve_success_and_version_increment(api):
    """PRD §2.7: "A reserve request must carry `expected_agreement_version` matching the
    target agreement's current `version`." PRD §2.4: "a `version`, an integer that begins
    at 1 on creation and increments by exactly 1 on each mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_reserve_success_and_version_increment
    """
    F.create_container_model(size_code="C16")
    F.create_protection_plan(tier_code="NONE")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="oc@x.com")

    ag = validate_success(api.create_rental_agreement(
        create_rental_agreement_payload(cust["id"], depot["id"], size_code="C16"), DO), 201)
    assert ag["version"] == 1

    res = api.reserve_agreement(ag["id"], reserve_payload(ag["version"]), DO)
    reserved = validate_success(res, 200)
    assert reserved["lifecycle_status"] == "RESERVED"
    assert reserved["version"] == 2


def test_occ_payment_stale_version_rejected(api):
    """PRD §2.7: "A late-fee sweep can post a new late-fee charge and advance the
    agreement's `version` between the moment a client reads the balance and the moment it
    pays; if the supplied `expected_agreement_version` no longer matches, the payment is
    rejected with `ERR_STALE_VERSION` (HTTP 412) so the client re-reads the now-larger
    balance before paying."

    Design: Corner/cross_cutting_complexity_layers/occ_payment_stale_version_returns_412
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust_id = world["customer"]["id"]

    fresh = validate_success(api.get_rental_agreement(ag["id"], make_customer_headers(cust_id)), 200)
    stale_v = fresh["version"]

    F.advance_clock_and_sweep("2026-07-22T12:00:00Z")

    res = api.post_payment(
        ag["id"], payment_payload(19171, stale_v), make_customer_headers(cust_id))
    validate_error(res, "ERR_STALE_VERSION")
