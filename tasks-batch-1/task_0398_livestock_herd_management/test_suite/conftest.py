"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def herd_manager_headers():
    return TEST_USERS["herd_manager_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def sale_clerk_headers():
    return TEST_USERS["sale_clerk_headers"]


@pytest.fixture
def feedlot_operator_headers():
    return TEST_USERS["feedlot_operator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
