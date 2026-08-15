"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def eoc_manager_headers():
    return TEST_USERS["eoc_manager_headers"]


@pytest.fixture
def site_lead_headers():
    # Shared fallback: only safe for calls with no identity comparison.
    return TEST_USERS["site_lead_headers"]


@pytest.fixture
def intake_staff_headers():
    # Shared fallback: only safe for calls with no identity comparison.
    return TEST_USERS["intake_staff_headers"]


@pytest.fixture
def outreach_worker_headers():
    # Shared fallback: only safe for calls with no identity comparison.
    return TEST_USERS["outreach_worker_headers"]


@pytest.fixture
def medical_responder_headers():
    # Shared fallback: only safe for calls with no identity comparison.
    return TEST_USERS["medical_responder_headers"]


@pytest.fixture
def transport_coordinator_headers():
    return TEST_USERS["transport_coordinator_headers"]
