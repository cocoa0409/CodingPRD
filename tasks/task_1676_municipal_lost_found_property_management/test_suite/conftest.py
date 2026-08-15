"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def public_user_headers():
    return TEST_USERS["public_user_headers"]


@pytest.fixture
def claimant_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def property_custodian_headers():
    return TEST_USERS["property_custodian_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def release_officer_headers():
    return TEST_USERS["release_officer_headers"]


@pytest.fixture
def police_liaison_headers():
    return TEST_USERS["police_liaison_headers"]


@pytest.fixture
def auction_coordinator_headers():
    return TEST_USERS["auction_coordinator_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]
