"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; this module only
exposes test_helpers as pytest fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# --- Per-role fixtures (shared constants — fallback only) ---
# Tests that perform ownership-gated calls must use the per-instance
# builders (make_<role>_headers(actual_entity_id)) imported from
# test_helpers, not these shared fixtures. PRD §2.1.

@pytest.fixture
def admin_headers():
    """PlatformAdmin headers — opaque identity per PRD §2.1."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def regulatory_headers():
    """RegulatoryGateway headers — opaque identity per PRD §2.1."""
    return TEST_USERS["regulatory_headers"]


@pytest.fixture
def shared_vendor_admin_headers():
    """Shared-constant VendorAdmin headers — only safe when the test does NOT
    exercise vendor ownership (e.g., role-permission negative tests)."""
    return TEST_USERS["vendor_admin_headers"]


@pytest.fixture
def shared_prescription_reviewer_headers():
    """Shared-constant PrescriptionReviewer headers — only safe for
    role-permission tests; ownership/SOD-gated tests must use
    make_prescription_reviewer_headers(pharmacist_id)."""
    return TEST_USERS["prescription_reviewer_headers"]


@pytest.fixture
def shared_pharmacist_re_reviewer_headers():
    """Shared-constant PharmacistReReviewer headers — only safe for
    role-permission tests; assignment-gated tests must use
    make_pharmacist_re_reviewer_headers(pharmacist_id)."""
    return TEST_USERS["pharmacist_re_reviewer_headers"]


@pytest.fixture
def shared_pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def shared_customer_headers():
    """Shared-constant Customer headers — only safe for role-permission tests;
    every order operation must use make_customer_headers(customer_id)."""
    return TEST_USERS["customer_headers"]
