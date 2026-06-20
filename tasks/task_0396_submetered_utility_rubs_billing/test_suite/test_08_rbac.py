"""Role-based access control: missing headers, forbidden roles, tenant ownership.

Covers queue-B section: rbac corner instances.
"""
from test_helpers import (
    validate_error, get_success_data, TEST_USERS, ApiErrorId, make_tenant_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# rbac / missing_user_context_header_returns_401
# --------------------------------------------------------------------------- #
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. `X-User-ID` identifies the acting user, and
    `X-User-Role` declares the operational capacity under which the request is
    made. If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_returns_401
    """
    validate_error(
        api.create_property({"name": "NoAuth", "state_code": "CA"}, headers={}),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
    )


# --------------------------------------------------------------------------- #
# rbac / meter_tech_cannot_create_property_returns_forbidden
# --------------------------------------------------------------------------- #
def test_meter_tech_cannot_create_property(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §2.1: "A `MeterTech` is a field technician who creates and submits meter
    reads and re-reads."

    Design: Corner/rbac/meter_tech_cannot_create_property_returns_forbidden
    """
    validate_error(
        api.create_property(
            {"name": "TechProp", "state_code": "CA"}, TEST_USERS["meter_tech_headers"]
        ),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value,
    )


# --------------------------------------------------------------------------- #
# rbac / auditor_cannot_approve_vendor_bill_returns_forbidden
# --------------------------------------------------------------------------- #
def test_auditor_cannot_approve_vendor_bill(api):
    """PRD §2.1: "An `Auditor` has read-only oversight across all resources."
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/auditor_cannot_approve_vendor_bill_returns_forbidden
    """
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="RUBS")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=20000)
    validate_error(
        api.approve_vendor_bill(vb["id"], TEST_USERS["auditor_headers"]),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value,
    )


# --------------------------------------------------------------------------- #
# rbac / tenant_pays_another_tenants_statement_returns_not_statement_owner
# --------------------------------------------------------------------------- #
def test_tenant_paying_another_tenants_statement_rejected(api):
    """PRD §2.1: "A `Tenant` may act only on disputes, payments, statements, and
    lease-notice operations belonging to a lease whose `tenant_user_id` equals
    the caller's `X-User-ID`; any attempt by a tenant to act on a statement,
    dispute, payment, or lease that does not belong to them is rejected with
    `ERR_NOT_STATEMENT_OWNER`."

    Design: Corner/rbac/tenant_pays_another_tenants_statement_returns_not_statement_owner
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=7059, tenant_user_id="tOWN")
    stmt = bundle["statement"]
    other = make_tenant_headers("tOTHER")
    validate_error(
        api.post_payment(
            stmt["id"], {"amount_cents": 6000, "expected_statement_version": stmt["version"]}, other
        ),
        ApiErrorId.ERR_NOT_STATEMENT_OWNER.value,
    )
