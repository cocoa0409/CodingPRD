"""Pytest fixtures exposing ``test_helpers`` infrastructure.

The runner manages ``PYTHONPATH`` and server lifecycle. This conftest
wires per-role headers and a session-scoped api client.

PRD §2.1 identity rules:
- ``CoreEnterpriseUser`` and ``SupplierUser`` are entity-backed; the
  shared headers below are FALLBACKS for tests that don't exercise
  ownership. Ownership-gated tests build headers via
  ``make_core_enterprise_headers(ce['id'])`` /
  ``make_supplier_headers(supplier['id'])``.
- The seven opaque-role headers are canonical.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the
    runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers — canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def credit_officer_headers():
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def risk_reviewer_headers():
    return TEST_USERS["risk_reviewer_headers"]


@pytest.fixture
def risk_reviewer_headers_alt():
    return TEST_USERS["risk_reviewer_headers_alt"]


@pytest.fixture
def credit_approver_headers():
    return TEST_USERS["credit_approver_headers"]


@pytest.fixture
def credit_approver_headers_alt():
    return TEST_USERS["credit_approver_headers_alt"]


@pytest.fixture
def funder_headers():
    return TEST_USERS["funder_headers"]


@pytest.fixture
def collection_manager_headers():
    return TEST_USERS["collection_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — for tests that DO NOT exercise
# ownership (missing-auth, wrong-role, missing-resource probes only).
# Ownership-gated tests build headers per-instance via the
# make_<role>_headers(entity_id) builders from test_helpers.
# ---------------------------------------------------------------------------
@pytest.fixture
def core_enterprise_user_fallback_headers():
    return TEST_USERS["core_enterprise_user_headers"]


@pytest.fixture
def supplier_user_fallback_headers():
    return TEST_USERS["supplier_user_headers"]
