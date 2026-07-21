"""Role-based access control: authentication, authorization, and ownership."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_client_payload, create_quote_payload,
    make_client_contact_headers, unauthenticated_headers,
)
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]
CARRIER = TEST_USERS["carrier_headers"]


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of the recognized roles, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/list_clients_missing_auth_returns_unauthenticated
    """
    resp = api.list_clients(unauthenticated_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_wrong_role_create_client_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/create_client_wrong_role_forbidden
    """
    resp = api.create_client(create_client_payload(legal_name="Nope Co"), CARRIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_client_contact_wrong_owner_forbidden(api):
    """PRD §2.1: "for any election operation the server resolves the election's enrollment
    window and compares that window's client_id to X-User-ID; if they differ, the request
    is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/election_wrong_owner_forbidden
    """
    owner, policy = fx.setup_client_with_active_policy(legal_name="Owner Co")
    other = fx.create_client(legal_name="Other Co")
    window = fx.create_open_window(owner["id"])
    member = fx.create_member(owner["id"], full_name="Owned Member")
    # ClientContact acts as the OTHER client id -> ownership check fails.
    resp = api.create_election(
        {"window_id": window["id"], "census_member_id": member["id"],
         "policy_id": policy["id"], "coverage_tier": "EMPLOYEE_ONLY"},
        make_client_contact_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_carrier_rep_submits_quote_allowed(api):
    """PRD §3.2: "A CarrierRep submits a quote against an open campaign, supplying the
    campaign_id, the carrier_name, the quoted composite monthly_premium_cents (which must
    be at least 1), and the carrier-offered commission_rate_pct expressed as a fraction
    between 0 and 1 inclusive (for example, 0.04 for four percent). A submitted quote begins
    in SUBMITTED."

    Design: Corner/rbac/carrier_rep_submits_quote_allowed
    """
    client = fx.create_client(legal_name="QuoteOK Co")
    camp = validate_success(api.create_campaign(
        {"client_id": client["id"], "coverage_line": "LIFE",
         "target_effective_date": "2026-01-01"}, CONSULTANT), 201)
    validate_success(api.open_campaign(camp["id"], CONSULTANT))
    data = validate_success(api.create_quote(
        create_quote_payload(camp["id"], carrier_name="Life Co",
                             monthly_premium_cents=150_000, commission_rate_pct=0.06),
        CARRIER), 201)
    assert data["status"] == "SUBMITTED"
