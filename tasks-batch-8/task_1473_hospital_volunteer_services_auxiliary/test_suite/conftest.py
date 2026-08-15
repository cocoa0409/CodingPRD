"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]


@pytest.fixture
def screener2_headers():
    return TEST_USERS["screener2_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def treasurer2_headers():
    return TEST_USERS["treasurer2_headers"]


@pytest.fixture
def dept_head_headers():
    return TEST_USERS["dept_head_headers"]


@pytest.fixture
def dept_head2_headers():
    return TEST_USERS["dept_head2_headers"]
