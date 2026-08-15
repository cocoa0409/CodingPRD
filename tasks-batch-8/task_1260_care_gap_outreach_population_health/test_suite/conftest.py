"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def panel_manager_headers():
    return TEST_USERS["panel_manager_headers"]


@pytest.fixture
def quality_reviewer_headers():
    return TEST_USERS["quality_reviewer_headers"]


@pytest.fixture
def transport_coordinator_headers():
    return TEST_USERS["transport_coordinator_headers"]


@pytest.fixture
def reconciliation_bot_headers():
    return TEST_USERS["reconciliation_bot_headers"]
