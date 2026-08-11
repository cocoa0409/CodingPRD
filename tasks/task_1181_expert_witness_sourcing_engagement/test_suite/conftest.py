"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def conflict_analyst_headers():
    return TEST_USERS["conflict_analyst_headers"]


@pytest.fixture
def credential_analyst_headers():
    return TEST_USERS["credential_analyst_headers"]


@pytest.fixture
def billing_reviewer_headers():
    return TEST_USERS["billing_reviewer_headers"]


@pytest.fixture
def expert_headers():
    return TEST_USERS["expert_headers"]
