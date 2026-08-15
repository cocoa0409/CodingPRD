"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the test runner."""
    return api_client


@pytest.fixture
def house_admin_headers():
    return TEST_USERS["house_admin_headers"]


@pytest.fixture
def wardrobe_staff_headers():
    return TEST_USERS["wardrobe_staff_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def renter_contact_headers():
    # Fallback only: never use for ownership-gated calls; build per-renter
    # headers with make_renter_contact_headers(renter["id"]) instead.
    return TEST_USERS["renter_contact_headers"]
