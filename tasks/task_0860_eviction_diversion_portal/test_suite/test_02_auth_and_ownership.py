"""Authentication, authorization, ownership, and OCC on plan create (PRD §2.1, §2.6, §2.8)."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, build_user_headers,
    make_landlord_headers, make_tenant_headers, TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


def test_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role names a value that is
    not one of these seven roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/validations/missing_auth_returns_unauthenticated
    """
    ctx = fx.seed_parties(api)
    payload = f.create_case_payload(ctx["court"]["id"], ctx["landlord"]["id"],
                                    ctx["tenant"]["id"], filing_type="NONPAYMENT",
                                    claimed_arrears_cents=400000)
    resp = api.create_case(payload, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_tenant_cannot_enter_judgment_returns_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation ... the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)." PRD §4: POST /judgments is authorized for Judge only.

    Design: Corner/validations/tenant_cannot_enter_judgment_returns_unauthorized
    """
    ctx = fx.setup_in_litigation_case(api, claimed_arrears_cents=600000)
    resp = api.create_judgment(f.create_judgment_payload(ctx["case"]["id"], "POSSESSION"),
                               make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_landlord_not_owner_returns_unauthorized(api):
    """PRD §2.1: "ownership checks on any case-linked resource compare the case's
    landlord_id to X-User-ID, so a landlord may only act on cases they filed and
    their descendant artefacts."

    Design: Corner/validations/landlord_not_owner_returns_unauthorized
    """
    court = get_success_data(api.create_court(f.create_court_payload(), CLERK))
    ll_a = get_success_data(api.create_landlord(f.create_landlord_payload(name="LLA"), CLERK))
    ll_b = get_success_data(api.create_landlord(f.create_landlord_payload(name="LLB"), CLERK))
    tenant = get_success_data(api.create_tenant(f.create_tenant_payload(), CLERK))
    case = get_success_data(api.create_case(
        f.create_case_payload(court["id"], ll_a["id"], tenant["id"],
                              filing_type="NONPAYMENT", claimed_arrears_cents=600000),
        make_landlord_headers(ll_a["id"])))
    get_success_data(api.transition_case(case["id"], {"to_status": "SERVED"}, CLERK))
    get_success_data(api.create_answer(f.create_answer_payload(case["id"]),
                                       make_tenant_headers(tenant["id"])))
    version = get_success_data(api.get_case(case["id"], CLERK))["version"]
    # Landlord B (not the case owner) tries to open a plan on landlord A's case.
    resp = api.create_payment_plan(
        f.create_payment_plan_payload(case["id"], 600000, 6, version, proposed_by="LANDLORD"),
        make_landlord_headers(ll_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_plan_create_stale_case_version_returns_stale_version(api):
    """PRD §2.6: "The server compares it to the case's current version; if they do not
    match ... the create is rejected with ERR_STALE_VERSION (HTTP 412)." PRD §2.6: "On
    a successful create, the case's version is incremented by 1."

    Design: Corner/validations/plan_create_stale_case_version_returns_stale_version
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    stale_version = ctx["case"]["version"]
    # First create advances Case.version, so the captured version is now stale.
    fx.open_plan(api, ctx, 600000, 6, expected_case_version=stale_version)
    resp = api.create_payment_plan(
        f.create_payment_plan_payload(ctx["case"]["id"], 600000, 6, stale_version,
                                      proposed_by="LANDLORD"),
        make_landlord_headers(ctx["landlord"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
