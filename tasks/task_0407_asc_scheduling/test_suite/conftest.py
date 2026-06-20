"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def preop_nurse_headers():
    return TEST_USERS["preop_nurse_headers"]


@pytest.fixture
def or_manager_headers():
    return TEST_USERS["or_manager_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]
