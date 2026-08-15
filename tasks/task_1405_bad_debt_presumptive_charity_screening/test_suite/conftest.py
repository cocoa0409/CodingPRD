"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def collector_headers():
    return TEST_USERS["collector_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def agency_headers():
    return TEST_USERS["agency_headers"]
