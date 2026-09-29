"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trustee_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_alt_headers():
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
