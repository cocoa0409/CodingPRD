"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH; tests
assume the server is already running and reachable.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def po_headers():
    """ProvostOfficer identity used by fixtures as the case creator."""
    return TEST_USERS["provost_creator_headers"]


@pytest.fixture
def po_decider_headers():
    """Independent ProvostOfficer identity for decision recording (SoD)."""
    return TEST_USERS["provost_decider_headers"]


@pytest.fixture
def po_other_headers():
    return TEST_USERS["provost_other_headers"]


@pytest.fixture
def appeal_officer_headers():
    return TEST_USERS["appeal_officer_headers"]


@pytest.fixture
def records_officer_headers():
    return TEST_USERS["records_officer_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def reader_headers():
    """Generic authenticated reader for Any-covered GET endpoints."""
    return TEST_USERS["reader_headers"]
