"""Authentication, RBAC, response envelope, ownership (PRD §2.1–§2.4).

Covers:
- Missing or empty ``X-User-ID`` / ``X-User-Role`` headers
- Unknown role names
- Endpoint authorization (wrong role)
- Entity-backed ownership (CoreEnterpriseUser, SupplierUser)
- Path/referenced-FK existence
- Success envelope shape
- Pagination defaults
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_core_enterprise_payload,
    create_payable_confirmation_payload,
    create_supplier_payload,
    iso_in_days,
    make_core_enterprise_headers,
    make_supplier_headers,
    register_supplier,
    setup_active_supplier,
    setup_approved_core_enterprise,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Missing or empty user-context headers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [
    {},
    {"X-User-ID": "any-user"},
    {"X-User-Role": "PlatformAdmin"},
    {"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
    {"X-User-ID": "any-user", "X-User-Role": ""},
])
def test_missing_or_empty_auth_headers_rejected(api, headers):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with ERR_AUTH_HEADER_MISSING and HTTP status 401."
    """
    res = api.create_core_enterprise(create_core_enterprise_payload(),
                                     headers)
    validate_error(res, ApiErrorId.ERR_AUTH_HEADER_MISSING.value)


@pytest.mark.parametrize("bad_role", [
    "platformadmin",       # case sensitive — lowercase rejected
    "Admin",               # not in enum
    "SuperUser",
    "Unknown",
])
def test_unknown_role_rejected(api, bad_role):
    """PRD §2.1: "If X-User-Role is present but is not one of the nine
    recognised role names, the request is rejected with
    ERR_AUTH_ROLE_UNKNOWN and HTTP status 401."
    """
    headers = build_user_headers("any-user", bad_role)
    res = api.create_core_enterprise(create_core_enterprise_payload(),
                                     headers)
    validate_error(res, ApiErrorId.ERR_AUTH_ROLE_UNKNOWN.value)


# ---------------------------------------------------------------------------
# Endpoint authorization — wrong role
# ---------------------------------------------------------------------------
def test_create_core_enterprise_requires_credit_officer(
    api, compliance_officer_headers,
):
    """PRD §4: "POST /scf/core-enterprises ... Authorized Role(s):
    CreditOfficer." PRD §2.1: "When a role is recognised but is not
    authorized to invoke the requested endpoint per §4 and the role
    narratives below, the response is ERR_FORBIDDEN with HTTP status
    403."
    """
    res = api.create_core_enterprise(create_core_enterprise_payload(),
                                     compliance_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_create_supplier_requires_platform_admin(
    api, credit_officer_headers,
):
    """PRD §4: "POST /scf/suppliers ... Authorized Role(s):
    PlatformAdmin." PRD §2.1: "the response is ERR_FORBIDDEN with HTTP
    status 403."
    """
    res = api.create_supplier(create_supplier_payload(),
                              credit_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_kyc_supplier_requires_compliance_officer(
    api, credit_officer_headers, platform_admin_headers,
):
    """PRD §4: "POST /scf/suppliers/{id}/kyc ... Authorized Role(s):
    ComplianceOfficer." Other roles (e.g., CreditOfficer) are not
    authorized.
    """
    supplier = register_supplier(tier_to_core=1)
    res = api.kyc_supplier(supplier["id"],
                           {"kyc_status": "PASSED", "aml_risk_score": 0.1},
                           credit_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_advance_clock_requires_platform_admin(
    api, credit_officer_headers,
):
    """PRD §4: "POST /scf/_clock/advance ... Authorized Role(s):
    PlatformAdmin." A CreditOfficer is not authorized."""
    res = api.advance_clock({"to": "2099-01-01T00:00:00.000Z"},
                            credit_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Entity-backed ownership (PRD §2.1)
# ---------------------------------------------------------------------------
def test_core_enterprise_user_owns_only_its_own_confirmations(api):
    """PRD §2.1: "An entity-backed actor who attempts to operate on a
    resource it does not own is rejected with ERR_OWNERSHIP_VIOLATION
    and HTTP status 403."

    Build two CoreEnterprises. CE_A uploads a PayableConfirmation; CE_B's
    user attempts to confirm CE_A's row — must be rejected.
    """
    ce_a = setup_approved_core_enterprise()
    ce_b = setup_approved_core_enterprise()
    supplier = setup_active_supplier(tier_to_core=1)
    pc_payload = create_payable_confirmation_payload(
        core_enterprise_id=ce_a["id"], supplier_id=supplier["id"],
        amount_cents=1_000_000, due_date=iso_in_days(60),
    )
    upload_res = api.create_payable_confirmation(
        pc_payload, make_core_enterprise_headers(ce_a["id"]),
    )
    pc = validate_success(upload_res, expected_status=201)
    # CE_B tries to confirm CE_A's confirmation: identity-threaded to CE_B.
    confirm_res = api.confirm_payable_confirmation(
        pc["id"], make_core_enterprise_headers(ce_b["id"]),
    )
    validate_error(confirm_res, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)


def test_supplier_user_owns_only_its_own_receivables(api):
    """PRD §2.1: "When X-User-Role is SupplierUser, X-User-ID is the id
    of the acting Supplier; ownership checks on a Receivable or
    FinancingApplication compare the resource's supplier_id to
    X-User-ID." Mismatched ids yield ERR_OWNERSHIP_VIOLATION.

    Supplier A registers a receivable; Supplier B's user attempts to
    pledge it.
    """
    from test_helpers import (
        register_receivable,
        setup_confirmed_payable_confirmation,
    )
    bundle = setup_confirmed_payable_confirmation()
    sup_a = bundle["supplier"]
    receivable = register_receivable(sup_a, bundle["confirmation"])
    sup_b = setup_active_supplier(tier_to_core=1)
    res = api.pledge_receivable(
        receivable["id"], make_supplier_headers(sup_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)


# ---------------------------------------------------------------------------
# Existence checks — path resource and referenced FK
# ---------------------------------------------------------------------------
def test_get_unknown_core_enterprise_returns_not_found(
    api, credit_officer_headers,
):
    """PRD §2.4: "The id of a path resource is validated for existence
    before any other check beyond authentication and authorization; a
    missing path resource yields ERR_NOT_FOUND with HTTP status 404."
    """
    res = api.get_core_enterprise(NON_EXISTENT_UUID, credit_officer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_supplier_with_unknown_parent_returns_referenced_not_found(
    api, platform_admin_headers,
):
    """PRD §2.4: "Where a request body references another entity by its
    id ... and the referenced entity does not exist, the response is
    ERR_REFERENCED_NOT_FOUND, also HTTP status 404."
    """
    payload = create_supplier_payload(
        tier_to_core=2, parent_supplier_id=NON_EXISTENT_UUID,
    )
    res = api.create_supplier(payload, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_REFERENCED_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Success envelope — created resources return 201 + standard envelope
# ---------------------------------------------------------------------------
def test_create_core_enterprise_returns_201_with_data_envelope(
    api, credit_officer_headers,
):
    """PRD §2.2: "successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" —
    meta + response_type + data. PRD §4: POST /scf/core-enterprises
    returns 201.
    """
    res = api.create_core_enterprise(create_core_enterprise_payload(),
                                     credit_officer_headers)
    data = validate_success(res, expected_status=201)
    assert data.get("onboarding_status") == "PENDING", (
        "PRD §3.1: 'The new resource is created with onboarding_status "
        "of PENDING'."
    )


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def test_list_payable_confirmations_pagination_envelope(
    api, platform_admin_headers,
):
    """PRD §2.3: "The pagination block within meta always carries
    limit, offset, total_count, and has_more."
    """
    res = api.list_payable_confirmations(platform_admin_headers,
                                         params={"limit": 5, "offset": 0})
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert meta["limit"] == 5
    assert meta["offset"] == 0
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)
