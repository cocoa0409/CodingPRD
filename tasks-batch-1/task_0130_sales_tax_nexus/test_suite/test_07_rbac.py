"""Role-based access control: exclusive-operation denials and unauthenticated
requests.

Queue B: rbac section.
"""
import pytest

from test_helpers import (
    build_user_headers,
    make_seller_headers,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_tax_jurisdiction_payload
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def test_seller_cannot_create_tax_jurisdiction_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/seller_cannot_create_tax_jurisdiction_returns_unauthorized
    """
    seller = fx.create_seller(origin_state_code="CA")
    res = api.create_tax_jurisdiction(
        create_tax_jurisdiction_payload(), make_seller_headers(seller["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_preparer_cannot_accept_return_returns_unauthorized(api):
    """PRD §2.1: "A `TaxPreparer` drafts and reopens tax returns and may accrue use tax, but may never approve or file a return — that separation is the core segregation-of-duties control."

    Design: Corner/rbac/preparer_cannot_accept_return_returns_unauthorized
    """
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    ret = fx.create_draft_return(seller["id"], ca["id"])
    res = api.accept_tax_return(ret["id"], TEST_USERS["preparer_headers"])
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    headers = build_user_headers("nobody", "Ghost")
    res = api.list_tax_jurisdictions(headers)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
