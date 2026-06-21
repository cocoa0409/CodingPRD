"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def revenue_manager_headers():
    return TEST_USERS["revenue_manager_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def night_auditor_headers():
    return TEST_USERS["night_auditor_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]
