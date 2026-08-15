"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def director_2_headers():
    return TEST_USERS["director_2_headers"]


@pytest.fixture
def assistant_headers():
    return TEST_USERS["assistant_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def equipment_headers():
    return TEST_USERS["equipment_headers"]


@pytest.fixture
def reader_headers():
    """Reads marked Any in PRD §4 accept every declared role; a director
    credential is the canonical reader used throughout the suite."""
    return TEST_USERS["reader_headers"]
