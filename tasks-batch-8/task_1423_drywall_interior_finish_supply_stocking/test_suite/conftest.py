"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def foreman_headers():
    return TEST_USERS["foreman_headers"]


@pytest.fixture
def contractor_admin_headers():
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def accounts_receivable_headers():
    return TEST_USERS["accounts_receivable_headers"]


@pytest.fixture
def warehouse_manager_headers():
    return TEST_USERS["warehouse_manager_headers"]
