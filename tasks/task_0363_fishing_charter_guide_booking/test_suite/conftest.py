"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dock_master_headers():
    return TEST_USERS["dock_master_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def captain_headers_shared():
    """Shared-constant Captain headers — only for tests that do NOT exercise
    ownership (e.g., 403-forbidden-role). Ownership-gated calls must use
    make_captain_headers(captain_id)."""
    return TEST_USERS["captain_headers"]


@pytest.fixture
def customer_headers_shared():
    """Shared-constant Customer headers — only for tests that do NOT exercise
    ownership. Ownership-gated calls must use make_customer_headers(customer_id)."""
    return TEST_USERS["customer_headers"]
