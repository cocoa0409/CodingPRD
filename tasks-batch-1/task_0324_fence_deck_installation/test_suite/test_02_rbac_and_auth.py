"""Authentication and role-based access control claims.

Translates Corner/rbac instances.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, anonymous_headers,
    create_customer, create_project,
    create_customer_payload, create_project_payload, create_line_item_payload,
    make_customer_headers,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]


def test_estimator_cannot_create_project(api):
    """PRD §2.1: "a `ProjectManager` owns project creation and cancellation".
    PRD §2.1: "When a request is well-authenticated but the acting role is not permitted to perform the requested operation, the response is `ERR_FORBIDDEN`."

    Design: Corner/rbac/estimator_cannot_create_project
    """
    cust = create_customer()
    resp = api.create_project(
        create_project_payload(cust["id"], site_address="23 Rb", job_type="FENCE"), EST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_customer_cannot_accept_other_customers_estimate(api):
    """PRD §2.1: "A `Customer` may accept estimates and file warranty claims, but only on a project whose `customer_id` equals their own `X-User-ID`; an attempt to act on someone else's project is rejected with `ERR_FORBIDDEN`."
    PRD §3.3: "the acting `X-User-ID` must equal the project's `customer_id` or the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_accept_other_customers_estimate
    """
    cust_a = create_customer(full_name="Own A", email="owna@x.com")
    cust_b = create_customer(full_name="Own B", email="ownb@x.com")
    proj = create_project(cust_a["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    get_success_data(api.create_line_item(
        create_line_item_payload(est["id"], quantity_units=100), EST))
    get_success_data(api.price_estimate(proj["id"], est["id"], EST))
    # Customer B (wrong owner) attempts to accept.
    resp = api.accept_estimate(proj["id"], est["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    # Estimate remains PRICED (unchanged by the forbidden accept).
    est_state = get_success_data(api.list_estimates(proj["id"], EST))
    matching = [e for e in est_state if e["id"] == est["id"]]
    assert matching and matching[0]["status"] == "PRICED"


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_customer(
        create_customer_payload(full_name="NoRole", email="nr@x.com"),
        anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
