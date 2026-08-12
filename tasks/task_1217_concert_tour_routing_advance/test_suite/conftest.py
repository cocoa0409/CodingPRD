"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def promoter_headers():
    return TEST_USERS["promoter_headers"]


@pytest.fixture
def venue_rep_headers():
    return TEST_USERS["venue_rep_headers"]


@pytest.fixture
def settlement_accountant_headers():
    return TEST_USERS["settlement_accountant_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
