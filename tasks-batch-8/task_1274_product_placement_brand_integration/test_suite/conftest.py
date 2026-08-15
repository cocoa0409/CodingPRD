"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and injects API_BASE_URL; the client below
is session-scoped and never starts or stops the server.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def production_headers():
    return TEST_USERS["production_headers"]


@pytest.fixture
def production_alt_headers():
    return TEST_USERS["production_alt_headers"]


@pytest.fixture
def network_headers():
    return TEST_USERS["network_headers"]


@pytest.fixture
def clearance_headers():
    return TEST_USERS["clearance_headers"]


@pytest.fixture
def clearance_alt_headers():
    return TEST_USERS["clearance_alt_headers"]


@pytest.fixture
def verifier_headers():
    return TEST_USERS["verifier_headers"]


@pytest.fixture
def verifier_alt_headers():
    return TEST_USERS["verifier_alt_headers"]


@pytest.fixture
def brand_rep_headers():
    return TEST_USERS["brand_rep_headers"]
