"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def intended_parent_actor_headers():
    return TEST_USERS["intended_parent_actor_headers"]


@pytest.fixture
def carrier_actor_headers():
    return TEST_USERS["carrier_actor_headers"]
