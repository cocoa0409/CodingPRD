"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def state_admin_headers():
    return TEST_USERS["state_admin_headers"]


@pytest.fixture
def state_examiner_headers():
    return TEST_USERS["state_examiner_headers"]


@pytest.fixture
def state_approver_headers():
    return TEST_USERS["state_approver_headers"]


@pytest.fixture
def holder_headers():
    return TEST_USERS["holder_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def recovery_agent_headers():
    return TEST_USERS["recovery_agent_headers"]
