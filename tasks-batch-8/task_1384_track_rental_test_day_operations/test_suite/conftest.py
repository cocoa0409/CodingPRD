"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def trackops_headers():
    return TEST_USERS["trackops_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]
