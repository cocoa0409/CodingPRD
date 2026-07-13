"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner
    (the server is killed and relaunched before every individual test)."""
    return api_client


@pytest.fixture
def carrier_headers():
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def permit_officer_headers():
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def bridge_engineer_headers():
    return TEST_USERS["bridge_engineer_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def dot_admin_headers():
    return TEST_USERS["dot_admin_headers"]
