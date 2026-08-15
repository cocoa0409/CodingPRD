"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import fixtures as _fixtures


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_logical_clock_tracker():
    """The harness restarts the server (and its logical clock, which starts at
    2026-08-01T00:00:00Z per PRD §2.4) before every test; keep the client-side
    tracker in fixtures.py aligned with that fresh start."""
    _fixtures.reset_clock_tracker()
    yield


@pytest.fixture
def unit_admin_headers():
    return TEST_USERS["unit_admin_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def endoscopist_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["endoscopist_headers"]


@pytest.fixture
def anesthesia_provider_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["anesthesia_provider_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def pathology_headers():
    return TEST_USERS["pathology_headers"]


@pytest.fixture
def quality_officer_headers():
    return TEST_USERS["quality_officer_headers"]
