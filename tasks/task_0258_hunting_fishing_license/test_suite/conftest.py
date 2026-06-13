"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def license_agent_headers():
    return TEST_USERS["license_agent_headers"]


@pytest.fixture
def draw_officer_headers():
    return TEST_USERS["draw_officer_headers"]


@pytest.fixture
def game_warden_headers():
    return TEST_USERS["game_warden_headers"]
