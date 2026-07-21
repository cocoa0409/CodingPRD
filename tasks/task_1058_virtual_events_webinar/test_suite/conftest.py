"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def other_organizer_headers():
    return TEST_USERS["other_organizer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def second_finance_admin_headers():
    return TEST_USERS["second_finance_admin_headers"]


@pytest.fixture
def attendee_headers():
    return TEST_USERS["attendee_headers"]


@pytest.fixture
def speaker_headers():
    return TEST_USERS["speaker_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]
