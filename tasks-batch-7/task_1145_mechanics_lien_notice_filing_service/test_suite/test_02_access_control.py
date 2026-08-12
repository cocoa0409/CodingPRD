"""Authentication and role-based access control (PRD §2.1, §2.10, §4)."""
from test_helpers import (
    ApiErrorId,
    create_company,
    create_party,
    create_project,
    make_customer_admin_headers,
    setup_filed_claim_with_sent_referral,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import create_jurisdiction_rule_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]
_COUNSEL = TEST_USERS["counsel_headers"]

MISSING_PROJECT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_missing_auth_header_returns_401():
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of these four roles is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.10: "1. **Authentication** — the `X-User-Role` header must be present
    and name a declared role, else `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    res = api.get_project(MISSING_PROJECT_ID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_customer_admin_cannot_decide_party():
    """PRD §4: "POST | `/lien/parties/{id}/decide` | Verify or fail a party's
    research | OpsAgent" and PRD §2.1: "A request whose role is not authorized
    for the targeted operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/customer_admin_cannot_decide_party
    """
    company = create_company(name="RB Co")
    project = create_project(company["id"], name="RB Job", contract_value_cents=100)
    party = create_party(project["id"], company["id"], "OWNER", verify=False)

    res = api.decide_party(
        party["id"], {"outcome": "VERIFIED"},
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    fetched = validate_success(api.get_party(party["id"], _OPS_AGENT), 200)
    assert fetched["research_status"] == "PENDING"


def test_ops_agent_cannot_create_jurisdiction_rule():
    """PRD §4: "POST | `/lien/jurisdiction-rules` | Publish the first rule for a
    (state_code, project_type) pair | PlatformAdmin" and PRD §2.1: "A request
    whose role is not authorized for the targeted operation is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/ops_agent_cannot_create_jurisdiction_rule
    """
    res = api.create_jurisdiction_rule(
        create_jurisdiction_rule_payload(), _OPS_AGENT
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_customer_admin_cross_company_access_forbidden():
    """PRD §2.1: "a `CustomerAdmin` may only access resources whose owning
    project's `company_id` equals their own `X-User-ID`; attempts against
    another company's resources are rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/customer_admin_cross_company_access_forbidden
    """
    company_a = create_company(name="A Co")
    company_b = create_company(name="B Co")
    project_b = create_project(company_b["id"], name="B Job", contract_value_cents=100)

    res = api.get_project(
        project_b["id"], make_customer_admin_headers(company_a["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_counsel_can_read_and_ops_cannot_respond():
    """PRD §4: "GET | `/lien/projects/{id}` | Get a project | All roles" and
    "POST | `/lien/foreclosure-referrals/{id}/respond` | Counsel accepts or
    declines the referral | Counsel"; PRD §2.1: "A request whose role is not
    authorized for the targeted operation is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/counsel_can_read_and_ops_cannot_respond
    """
    ctx = setup_filed_claim_with_sent_referral()

    seen = validate_success(api.get_project(ctx["project"]["id"], _COUNSEL), 200)
    assert seen["id"] == ctx["project"]["id"]

    res = api.respond_foreclosure_referral(
        ctx["referral"]["id"], {"outcome": "ACCEPTED"}, _OPS_AGENT
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
