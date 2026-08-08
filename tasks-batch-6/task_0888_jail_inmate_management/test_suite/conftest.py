"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def classification_headers():
    return TEST_USERS["classification_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def health_headers():
    return TEST_USERS["health_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def visitor_headers():
    return TEST_USERS["visitor_headers"]
