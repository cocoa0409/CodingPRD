"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def landlord_headers():
    # Shared fallback — for non-ownership calls only. Ownership-gated calls
    # must build headers from the real Landlord id via make_landlord_headers.
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def process_server_headers():
    return TEST_USERS["process_server_headers"]


@pytest.fixture
def deputy_headers():
    return TEST_USERS["deputy_headers"]


@pytest.fixture
def mediator_headers():
    return TEST_USERS["mediator_headers"]
