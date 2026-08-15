"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator2_headers():
    return TEST_USERS["coordinator2_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector2_headers():
    return TEST_USERS["inspector2_headers"]


@pytest.fixture
def forestry_headers():
    return TEST_USERS["forestry_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def hearing_headers():
    return TEST_USERS["hearing_headers"]


@pytest.fixture
def owner_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["owner_headers"]


@pytest.fixture
def contractor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["contractor_headers"]
