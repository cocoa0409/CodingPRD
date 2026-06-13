"""Role-based access control: exclusive-operation denials and invalid user context.

Covers Customer-exclusive payment recording, Estimator-exclusive estimate
finalization, and rejection of an undeclared user role.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    build_user_headers,
    create_project, add_surface, create_product,
    setup_estimated_project,
    TEST_DEFAULTS, TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
CUST = TEST_USERS["customer_headers"]

S1_DEPOSIT = TEST_DEFAULTS["S1_DEPOSIT_30PCT_CENTS"]  # 2674


def test_estimator_cannot_record_payment(api):
    """PRD §2.1: "A `Customer` is the homeowner who approves or rejects colors and change
    orders, pays the deposit and final balance, passes or fails walkthroughs, and files
    warranty claims."
    PRD §2.1: "When the headers are valid but the acting role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/estimator_cannot_record_payment
    """
    _, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    # POST /painting/payments is Customer-exclusive; an Estimator is forbidden.
    res = api.create_payment(
        {"project_id": project["id"], "kind": "DEPOSIT", "amount_cents": S1_DEPOSIT}, EST)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_customer_cannot_finalize_estimate(api):
    """PRD §2.1: "An `Estimator` authors scope — paint products, projects, surfaces, color
    proposals, the frozen estimate, and change orders."
    PRD §2.1: "When the headers are valid but the acting role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_finalize_estimate
    """
    product = create_product()
    project = create_project()
    add_surface(project["id"], product["id"])
    # finalize-estimate is Estimator-exclusive; a Customer is forbidden.
    res = api.finalize_estimate(project["id"], CUST)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`
    (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    intruder_headers = build_user_headers("test-intruder-1", "Intruder")
    res = api.list_projects(intruder_headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT", expected_status=401)
