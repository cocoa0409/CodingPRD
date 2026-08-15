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
def quality_headers():
    return TEST_USERS["quality_headers"]


@pytest.fixture
def quality2_headers():
    return TEST_USERS["quality2_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def compliance2_headers():
    return TEST_USERS["compliance2_headers"]


@pytest.fixture
def surgeon_headers():
    return TEST_USERS["surgeon_headers"]


@pytest.fixture
def surgeon2_headers():
    return TEST_USERS["surgeon2_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
