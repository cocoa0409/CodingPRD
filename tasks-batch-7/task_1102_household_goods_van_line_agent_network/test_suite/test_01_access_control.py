"""Access control: authentication, role authorization, ownership scoping (PRD 2.1, 2.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_agent_payload,
    create_customer_payload,
    create_estimate_payload,
    create_order_payload,
    create_published_tariff,
    create_tariff_payload,
    get_success_data,
    make_customer_headers,
    make_hauling_agent_headers,
    make_claims_adjuster_headers,
    setup_registered_order,
    issue_estimate,
    validate_error,
    api_client as _api,
)

ADMIN_ID = "vl-admin-1"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or presenting a role
    outside these eight, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_missing_auth_headers_returns_unauthenticated
    """
    from test_helpers import TEST_USERS, create_agent

    create_agent(["BOOKING"])
    resp = api.list_agents(None)  # no X-User-ID / X-User-Role headers at all
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_role_denial_matrix_sample(api):
    """PRD section 2.1: "A request whose role is not among the roles authorized
    for the target endpoint — or, for an entity-backed role, whose `X-User-ID`
    does not resolve to an existing entity of the backing type — is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 2.10: "Every request is evaluated against a fixed validation
    pipeline, and a request rejected at an earlier stage never reaches a later one."

    Design: Corner/rbac/role_denial_matrix_sample
    """
    from test_helpers import TEST_USERS, create_agent, create_customer

    admin = TEST_USERS["van_line_admin_headers"]
    cust = create_customer()
    haul = create_agent(["HAULING"])

    # Customer cannot register agents (POST /agents is VanLineAdmin-only).
    r1 = api.create_agent(
        create_agent_payload(legal_name="Nope"), make_customer_headers(cust["id"])
    )
    validate_error(r1, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # HaulingAgent cannot register orders (POST /orders is BookingAgent-only);
    # the role check fires before the nonexistent tariff is even considered.
    r2 = api.create_order(
        create_order_payload(cust["id"], NON_EXISTENT_UUID, pricing_mode="BINDING"),
        make_hauling_agent_headers(haul["id"]),
    )
    validate_error(r2, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # ClaimsAdjuster cannot create tariffs (POST /tariffs is VanLineAdmin-only).
    r3 = api.create_tariff(create_tariff_payload(), make_claims_adjuster_headers("adj-1"))
    validate_error(r3, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # Sanity: the same writes succeed for an authorized role.
    ok = api.create_tariff(create_tariff_payload(), admin)
    assert ok.status_code == 201, f"setup sanity tariff create failed: {ok.text}"


def test_ownership_scoping_other_customers_order(api):
    """PRD section 2.1: "a `Customer` caller's `X-User-ID` must equal the order's
    `customer_id`; the opaque roles (`VanLineAdmin`, `ClaimsAdjuster`, `Arbitrator`)
    are exempt from this scoping. A caller who passes role authorization but fails
    this ownership scope is likewise rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/ownership_scoping_other_customers_order
    """
    from test_helpers import create_customer

    ctx = setup_registered_order(pricing_mode="BINDING", mileage=900)
    estimate = issue_estimate(ctx, estimated_weight_lbs=5000)

    other_customer = create_customer()
    resp = api.accept_estimate(estimate["id"], make_customer_headers(other_customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # The estimate is untouched by the rejected call.
    from test_helpers import TEST_USERS

    current = get_success_data(api.get_estimate(estimate["id"], TEST_USERS["van_line_admin_headers"]))
    assert current["status"] == "ISSUED", f"estimate must remain ISSUED, got {current['status']}"
