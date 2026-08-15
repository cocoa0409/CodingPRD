"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def mod1_headers():
    return TEST_USERS["mod1_headers"]


@pytest.fixture
def mod2_headers():
    return TEST_USERS["mod2_headers"]


@pytest.fixture
def hub_headers():
    return TEST_USERS["hub_headers"]


@pytest.fixture
def steward_headers():
    # Fallback for the entity-backed Steward role: non-ownership tests only.
    return TEST_USERS["steward_headers"]


@pytest.fixture
def liaison_headers():
    # Fallback for the entity-backed SchoolLiaison role: non-ownership tests only.
    return TEST_USERS["liaison_headers"]
