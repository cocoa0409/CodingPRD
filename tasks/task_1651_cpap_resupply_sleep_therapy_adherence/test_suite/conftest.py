"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def respiratory_therapist_headers():
    return TEST_USERS["respiratory_therapist_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]
