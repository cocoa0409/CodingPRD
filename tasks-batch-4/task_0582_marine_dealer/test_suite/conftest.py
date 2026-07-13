"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def service_advisor_headers():
    return TEST_USERS["service_advisor_headers"]


@pytest.fixture
def parts_clerk_headers():
    return TEST_USERS["parts_clerk_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
