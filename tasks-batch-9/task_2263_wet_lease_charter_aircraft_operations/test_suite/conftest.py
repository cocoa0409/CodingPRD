"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lessor_ops_headers():
    return TEST_USERS["lessor_ops_headers"]


@pytest.fixture
def regulatory_authority_headers():
    return TEST_USERS["regulatory_authority_headers"]


@pytest.fixture
def maintenance_controller_headers():
    return TEST_USERS["maintenance_controller_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def second_billing_admin_headers():
    return TEST_USERS["second_billing_admin_headers"]


@pytest.fixture
def insurance_underwriter_headers():
    return TEST_USERS["insurance_underwriter_headers"]


@pytest.fixture
def lessee_headers():
    """Shared Lessee headers — only for tests that do not exercise ownership.
    Ownership-gated calls must use make_lessee_headers(<the Lessee row's id>)."""
    return TEST_USERS["lessee_headers"]
