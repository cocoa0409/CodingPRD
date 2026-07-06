"""Role-based access control (missing context, role authorization) and terminal
project-state lockdown on cancellation.

Queue B (corner): rbac + state_machines instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_customer_headers,
    create_customer, create_project, create_designer_payload,
    setup_presented_quote,
)

PA = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["install_coordinator_headers"]
FO = TEST_USERS["finance_officer_headers"]


def test_missing_user_context_rejected_first(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_MISSING_USER_CONTEXT."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    resp = api.get_project(NON_EXISTENT_UUID, headers={})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


def test_customer_cannot_create_designer(api):
    """PRD §2.1: "When a syntactically valid caller attempts an operation their
    role is not permitted to perform, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Design: Corner/rbac/customer_cannot_create_designer_forbidden
    """
    customer = create_customer(api)
    resp = api.create_designer(
        create_designer_payload(full_name="Sneaky"), make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_finance_officer_cannot_accept_quote(api):
    """PRD §2.1: "When a syntactically valid caller attempts an operation their
    role is not permitted to perform, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Design: Corner/rbac/financeofficer_cannot_accept_quote_forbidden
    """
    ctx = setup_presented_quote(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    resp = api.accept_quote(ctx["quote"]["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_cancel_already_cancelled_project_rejected(api):
    """PRD §3.8: "Cancellation is permitted from any state except the two terminal
    ones — a project that is already INSTALLED or CANCELLED cannot be cancelled
    again, and the attempt is refused with ERR_PROJECT_INVALID_STATE."

    Design: Corner/state_machines/project_cancel_when_already_cancelled_returns_invalid_state
    """
    customer = create_customer(api)
    project = create_project(api, customer["id"])
    validate_success(api.cancel_project(project["id"], {"cancel_reason": "first"}, IC), 200)
    resp = api.cancel_project(project["id"], {"cancel_reason": "second"}, IC)
    validate_error(resp, ApiErrorId.ERR_PROJECT_INVALID_STATE.value)
