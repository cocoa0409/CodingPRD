"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def podiatrist_headers():
    return TEST_USERS["podiatrist_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def payer_agent_headers():
    return TEST_USERS["payer_agent_headers"]
