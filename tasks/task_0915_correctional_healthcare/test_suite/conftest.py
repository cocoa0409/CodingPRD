"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def utilization_reviewer_headers():
    return TEST_USERS["utilization_reviewer_headers"]


@pytest.fixture
def peer_reviewer_headers():
    return TEST_USERS["peer_reviewer_headers"]


@pytest.fixture
def custody_officer_headers():
    return TEST_USERS["custody_officer_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["health_services_admin_headers"]


@pytest.fixture
def grievance_coordinator_headers():
    return TEST_USERS["grievance_coordinator_headers"]


@pytest.fixture
def no_auth_headers():
    """Headers carrying neither X-User-ID nor X-User-Role."""
    return dict(NO_AUTH_HEADERS)
