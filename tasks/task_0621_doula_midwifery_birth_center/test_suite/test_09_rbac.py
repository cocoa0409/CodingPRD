"""Role-based access control (queue B: Corner / rbac).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, build_user_headers, fixtures,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
ADMIN = TEST_USERS["center_admin_headers"]


# ---- midwife_cannot_register_client ----
def test_midwife_cannot_register_client(api):
    """PRD §2.1: "When both headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."
    PRD §2.1: "An IntakeCoordinator owns client intake, episode opening, and visit
    scheduling."

    Design: Corner/rbac/midwife_cannot_register_client
    """
    resp = api.create_client(f.create_client_payload(), MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---- billing_clerk_cannot_activate_episode ----
def test_billing_clerk_cannot_activate_episode(api):
    """PRD §2.1: "A Midwife owns the clinical lifecycle — activation, screening completion,
    birth recording, hospital transfer, and care completion."
    PRD §2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/billing_clerk_cannot_activate_episode
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    resp = api.activate_episode(ep_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["clinical_status"] == "PLANNING"


# ---- missing_auth_headers_unauthenticated ----
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_clients({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---- shared_get_allowed_for_billing_clerk ----
def test_shared_get_allowed_for_billing_clerk(api):
    """PRD §2.1: "Read access through any GET endpoint is open to all four roles."

    Design: Corner/rbac/shared_get_allowed_for_billing_clerk
    """
    client = fixtures.create_client()
    resp = api.get_client(client["id"], BILLING)
    data = validate_success(resp)
    assert data["id"] == client["id"]
