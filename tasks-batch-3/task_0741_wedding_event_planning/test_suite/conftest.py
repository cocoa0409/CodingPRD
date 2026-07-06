"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def client_headers():
    """Fallback Client headers — only for tests that do NOT exercise ownership."""
    return TEST_USERS["client_headers"]


@pytest.fixture
def vendor_headers():
    """Fallback Vendor headers — only for tests that do NOT exercise ownership."""
    return TEST_USERS["vendor_headers"]
