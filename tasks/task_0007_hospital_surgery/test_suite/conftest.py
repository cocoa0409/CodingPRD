"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def surgical_coordinator_headers():
    return TEST_USERS["surgical_coordinator_headers"]


@pytest.fixture
def department_head_headers():
    return TEST_USERS["department_head_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
