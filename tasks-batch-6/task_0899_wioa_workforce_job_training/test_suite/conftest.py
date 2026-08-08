"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def state_admin_headers():
    return TEST_USERS["state_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def fiscal_officer_headers():
    return TEST_USERS["fiscal_officer_headers"]


@pytest.fixture
def business_rep_headers():
    return TEST_USERS["business_rep_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
