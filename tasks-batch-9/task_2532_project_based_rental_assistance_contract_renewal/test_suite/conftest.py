"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def owner_agent_headers():
    """Placeholder owner-agent identity; real chains build headers from a created owner."""
    return TEST_USERS["owner_agent_headers"]


@pytest.fixture
def contract_administrator_headers():
    return TEST_USERS["contract_administrator_headers"]


@pytest.fixture
def contract_administrator_approver_headers():
    return TEST_USERS["contract_administrator_approver_headers"]


@pytest.fixture
def hud_field_office_headers():
    return TEST_USERS["hud_field_office_headers"]


@pytest.fixture
def pha_administrator_headers():
    return TEST_USERS["pha_administrator_headers"]
