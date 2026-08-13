"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["pm_headers"]


@pytest.fixture
def row_headers():
    return TEST_USERS["row_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]
