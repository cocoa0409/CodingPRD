"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def mill_manager_headers():
    return TEST_USERS["mill_manager_headers"]


@pytest.fixture
def nutritionist_headers():
    return TEST_USERS["nutritionist_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def quality_tech_headers():
    return TEST_USERS["quality_tech_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
