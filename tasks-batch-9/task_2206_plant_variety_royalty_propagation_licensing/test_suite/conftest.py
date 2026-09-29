"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def breeder_admin_headers():
    return TEST_USERS["breeder_admin_headers"]


@pytest.fixture
def licensing_officer_headers():
    return TEST_USERS["licensing_officer_headers"]


@pytest.fixture
def licensing_officer_two_headers():
    return TEST_USERS["licensing_officer_two_headers"]


@pytest.fixture
def licensing_officer_three_headers():
    return TEST_USERS["licensing_officer_three_headers"]


@pytest.fixture
def trial_coordinator_headers():
    return TEST_USERS["trial_coordinator_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def propagator_headers():
    """Fallback Propagator headers.  Ownership-gated calls must instead use
    make_propagator_headers(propagator_id)."""
    return TEST_USERS["propagator_headers"]
