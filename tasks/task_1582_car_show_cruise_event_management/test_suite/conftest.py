"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def desk_headers():
    return TEST_USERS["desk_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]
