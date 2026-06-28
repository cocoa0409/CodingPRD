"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def herd_manager_headers():
    return TEST_USERS["herd_manager_headers"]


@pytest.fixture
def parlor_tech_headers():
    return TEST_USERS["parlor_tech_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def coop_agent_headers():
    return TEST_USERS["coop_agent_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
