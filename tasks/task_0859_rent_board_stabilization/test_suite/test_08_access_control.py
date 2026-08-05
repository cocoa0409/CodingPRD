"""Access control and referential validation: authentication, authorization, tenant linkage.

Sources: Corner/rbac, Corner/validations.
"""
from test_helpers import (
    ApiErrorId,
    validate_error,
    make_hearing_officer_headers, make_tenant_headers,
    create_service_claim_payload,
    create_landlord, create_tenant, create_unit,
    setup_capital_petition_hearing,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or does not name a recognized role, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    landlord = create_landlord(api)
    resp = api.get_landlord(landlord["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_clerk_cannot_decide_hearing(api):
    """PRD §2.1: "If the role is recognized but is not permitted to invoke the requested
    operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: POST /rent-board/hearings/{id}/decide is authorized for HearingOfficer only.

    Design: Corner/rbac/clerk_cannot_decide_hearing
    """
    ctx = setup_capital_petition_hearing(api, base_rent_cents=300000, bedrooms=2,
                                         requested_cost_cents=1200000, amortization_months=120)
    resp = api.decide_hearing(ctx["hearing_id"], {"decision": "GRANT"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_service_claim_tenant_not_linked(api):
    """PRD §3.6: "The claiming tenant must be the unit's currently `ACTIVE` tenant — that
    is, an `ACTIVE` tenancy must link this `tenant_id` and `unit_id` — otherwise the claim
    is rejected with `ERR_TENANT_NOT_LINKED`."

    Design: Corner/validations/service_claim_tenant_not_linked
    """
    landlord = create_landlord(api)
    unit = create_unit(api, landlord["id"], base_rent_cents=300000, bedrooms=2)
    tenant2 = create_tenant(api)  # not linked to the unit by any tenancy
    resp = api.create_service_claim(
        create_service_claim_payload(unit["id"], tenant2["id"], "PEST", "MINOR"),
        make_tenant_headers(tenant2["id"]))
    validate_error(resp, ApiErrorId.ERR_TENANT_NOT_LINKED)
