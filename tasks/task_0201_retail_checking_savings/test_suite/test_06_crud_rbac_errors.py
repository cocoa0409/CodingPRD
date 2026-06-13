"""CRUD reads, RBAC, listing/pagination, and not-found errors (PRD §2.1–§2.8, §3).

Covers queue-B corner instances for entity creation/immutability, listing envelopes,
ownership and role enforcement, and resource not-found.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_account_holder_headers,
    make_officer_headers,
    make_teller_headers,
    make_headers,
    create_apy_tier,
    create_customer,
    create_submitted_application,
    open_account,
)
from test_helpers.factories import create_apy_tier_payload


def _holder(customer):
    return make_account_holder_headers(customer["id"])


# ===========================================================================
# Queue B — entities / get_customer_not_found_returns_404
# ===========================================================================
def test_get_customer_not_found_returns_404(api):
    """PRD §2.8: "The generic failure is `ERR_NOT_FOUND` (HTTP 404)".

    A GET for a non-existent customer UUID resolves no specialized kind on this read
    path and returns the generic ERR_NOT_FOUND.

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer(
        "00000000-0000-0000-0000-000000000000", make_teller_headers("teller-1")
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ===========================================================================
# Queue B — entities / apy_tier_immutable_no_version_field
# ===========================================================================
def test_apy_tier_carries_no_version_field(api):
    """PRD §2.4: "`ApyTier` is reference configuration that is written once and never
    mutated in place. An `ApyTier` therefore carries only `id` and `created_at`; it has
    no `updated_at` and no `version` field."

    Design: Corner/entities/apy_tier_immutable_no_version_field
    """
    created = create_apy_tier(code="CHK_STD", product_type="CHECKING")
    assert "version" not in created, "ApyTier must not carry a version field"
    assert "updated_at" not in created, "ApyTier must not carry an updated_at field"
    assert "id" in created and "created_at" in created

    listed, _meta = validate_paginated(
        api.list_apy_tiers(make_officer_headers(), params={"product_type": "CHECKING"})
    )
    tier = [t for t in listed if t["code"] == "CHK_STD"][0]
    assert "version" not in tier
    assert "updated_at" not in tier


# ===========================================================================
# Queue B — entities / list_accounts_pagination_envelope
# ===========================================================================
def test_list_accounts_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in its `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_accounts_pagination_envelope
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    open_account(customer_overrides={"tax_id_last4": "3131"})

    data, meta = validate_paginated(
        api.list_accounts(make_officer_headers(), params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


# ===========================================================================
# Queue B — endpoints / list_owners_by_customer_filter
# ===========================================================================
def test_list_owners_by_customer_filter(api):
    """PRD §3.3: "A first `AccountOwner` is created for that account with `ownership_role`
    of `PRIMARY`, `customer_id` taken from the application, and `is_active` true."

    GET /owners?customer_id=... returns that customer's PRIMARY AccountOwner row.

    Design: Corner/endpoints/list_owners_by_customer_filter
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={
        "legal_name": "Owner Filter", "tax_id_last4": "3434",
    })
    data, _meta = validate_paginated(
        api.list_account_owner_rows(make_officer_headers(), params={"customer_id": cust["id"]})
    )
    assert len(data) == 1
    assert data[0]["customer_id"] == cust["id"]
    assert data[0]["ownership_role"] == "PRIMARY"


# ===========================================================================
# Queue B — rbac / teller_cannot_approve_application
# ===========================================================================
def test_teller_cannot_approve_application(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: approve is authorized for ComplianceOfficer only.

    A Teller calling approve (a ComplianceOfficer-only op) is forbidden.

    Design: Corner/rbac/teller_cannot_approve_application
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust = create_customer(legal_name="Rbac Owner", tax_id_last4="3636")
    app = create_submitted_application(cust["id"], submitted_by="teller-1")
    res = api.approve_application(app["id"], make_teller_headers("teller-2"))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ===========================================================================
# Queue B — rbac / non_owner_account_holder_cannot_close
# ===========================================================================
def test_non_owner_account_holder_cannot_close(api):
    """PRD §2.1: "When an `AccountHolder` attempts a deposit, withdrawal, account close,
    stop-payment placement, or owner-management action on an account they do not actively
    own, the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403)."

    Customer B (a real but non-owning customer) attempts to close customer A's account.

    Design: Corner/rbac/non_owner_account_holder_cannot_close
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_a, acct_a = open_account(customer_overrides={
        "legal_name": "Owner A", "tax_id_last4": "3737",
    })
    cust_b = create_customer(legal_name="Owner B", tax_id_last4="3838")
    res = api.close_account(acct_a["id"], _holder(cust_b))
    validate_error(res, "ERR_NOT_ACCOUNT_OWNER", expected_status=403)


# ===========================================================================
# Queue B — rbac / missing_role_header_unauthenticated
# ===========================================================================
def test_unrecognized_role_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized role names,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.get_account(
        "00000000-0000-0000-0000-000000000000",
        make_headers("someone", "NotARole"),
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
