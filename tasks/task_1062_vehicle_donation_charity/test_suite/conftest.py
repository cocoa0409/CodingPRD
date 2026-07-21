"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def intake_agent_headers():
    return TEST_USERS["intake_agent_headers"]


@pytest.fixture
def title_clerk_headers():
    return TEST_USERS["title_clerk_headers"]


@pytest.fixture
def auction_manager_headers():
    return TEST_USERS["auction_manager_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_officer_bob_headers():
    return TEST_USERS["finance_officer_bob_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def donor_headers():
    return TEST_USERS["donor_headers"]


@pytest.fixture
def charity_admin_headers():
    return TEST_USERS["charity_admin_headers"]
