"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def permit_officer_headers():
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def second_officer_headers():
    return TEST_USERS["second_officer_headers"]


@pytest.fixture
def performer_headers():
    return TEST_USERS["performer_headers"]


@pytest.fixture
def audition_panelist_headers():
    return TEST_USERS["audition_panelist_headers"]


@pytest.fixture
def noise_inspector_headers():
    return TEST_USERS["noise_inspector_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
