"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def leasing_agent_headers():
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
