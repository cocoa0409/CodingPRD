"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def vdc_manager_headers():
    return TEST_USERS["vdc_manager_headers"]


@pytest.fixture
def bim_coordinator_headers():
    return TEST_USERS["bim_coordinator_headers"]


@pytest.fixture
def lead_engineer_headers():
    return TEST_USERS["lead_engineer_headers"]


@pytest.fixture
def facilities_manager_headers():
    return TEST_USERS["facilities_manager_headers"]


@pytest.fixture
def trade_model_author_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["trade_model_author_headers"]


@pytest.fixture
def fabrication_lead_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["fabrication_lead_headers"]
