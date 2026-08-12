"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def authenticity_officer_headers():
    return TEST_USERS["authenticity_officer_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def spectator_headers():
    return TEST_USERS["spectator_headers"]
