"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def research_manager_headers():
    return TEST_USERS["research_manager_headers"]


@pytest.fixture
def panel_ops_headers():
    return TEST_USERS["panel_ops_headers"]


@pytest.fixture
def field_coordinator_headers():
    return TEST_USERS["field_coordinator_headers"]


@pytest.fixture
def panelist_headers():
    return TEST_USERS["panelist_headers"]
