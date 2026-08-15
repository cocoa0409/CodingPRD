"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def researcher_headers():
    return TEST_USERS["researcher_headers"]


@pytest.fixture
def moderator_headers():
    """Shared fallback only — ownership-gated calls use make_moderator_headers."""
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def participant_headers():
    """Shared fallback only — ownership-gated calls use make_participant_headers."""
    return TEST_USERS["participant_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def legal_headers():
    return TEST_USERS["legal_headers"]
