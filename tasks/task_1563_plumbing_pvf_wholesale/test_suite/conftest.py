"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def counterrep_headers():
    return TEST_USERS["counterrep_headers"]


@pytest.fixture
def sales_headers():
    return TEST_USERS["sales_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]
