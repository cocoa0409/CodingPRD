"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def dmv_headers():
    return TEST_USERS["dmv_headers"]


@pytest.fixture
def driver_headers():
    """Fallback Driver headers — for non-ownership tests only (e.g. forbidden-role)."""
    return TEST_USERS["driver_headers"]
