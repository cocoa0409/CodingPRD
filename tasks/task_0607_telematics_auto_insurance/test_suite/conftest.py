"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def driver_headers():
    """Shared DriverUser headers — only for tests that do NOT exercise ownership."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def underwriting_headers():
    return TEST_USERS["underwriting_headers"]


@pytest.fixture
def claims_headers():
    return TEST_USERS["claims_headers"]
