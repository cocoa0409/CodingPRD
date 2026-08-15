"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def board_officer_headers():
    return TEST_USERS["board_officer_headers"]


@pytest.fixture
def board_member_headers():
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def managing_agent_headers():
    return TEST_USERS["managing_agent_headers"]


@pytest.fixture
def shareholder_headers():
    return TEST_USERS["shareholder_headers"]
