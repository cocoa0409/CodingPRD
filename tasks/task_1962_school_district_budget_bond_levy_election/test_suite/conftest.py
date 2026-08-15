"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def budget_analyst_headers():
    return TEST_USERS["budget_analyst_headers"]


@pytest.fixture
def business_manager_headers():
    return TEST_USERS["business_manager_headers"]


@pytest.fixture
def board_clerk_headers():
    return TEST_USERS["board_clerk_headers"]


@pytest.fixture
def superintendent_headers():
    return TEST_USERS["superintendent_headers"]


@pytest.fixture
def district_treasurer_headers():
    return TEST_USERS["district_treasurer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
