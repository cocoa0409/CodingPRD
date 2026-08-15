"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def card_office_admin_headers():
    return TEST_USERS["card_office_admin_headers"]


@pytest.fixture
def dining_manager_headers():
    return TEST_USERS["dining_manager_headers"]


@pytest.fixture
def bursar_headers():
    return TEST_USERS["bursar_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def pos_headers():
    return TEST_USERS["pos_headers"]


@pytest.fixture
def door_controller_headers():
    return TEST_USERS["door_controller_headers"]


@pytest.fixture
def cardholder_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["cardholder_headers"]


@pytest.fixture
def merchant_user_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["merchant_user_headers"]
