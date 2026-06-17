"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def yard_manager_headers():
    return TEST_USERS["yard_manager_headers"]


@pytest.fixture
def rental_agent_headers():
    return TEST_USERS["rental_agent_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]
