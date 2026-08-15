"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def volunteer_lead_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["volunteer_lead_headers"]


@pytest.fixture
def volunteer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def client_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["client_headers"]


@pytest.fixture
def referral_partner_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["referral_partner_headers"]
