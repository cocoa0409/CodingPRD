"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_alt_headers():
    return TEST_USERS["coordinator_alt_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def referring_provider_headers():
    return TEST_USERS["referring_provider_headers"]


@pytest.fixture
def specialist_provider_headers():
    return TEST_USERS["specialist_provider_headers"]
