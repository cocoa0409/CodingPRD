"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def post_supervisor_headers():
    return TEST_USERS["post_supervisor_headers"]


@pytest.fixture
def media_manager_headers():
    return TEST_USERS["media_manager_headers"]


@pytest.fixture
def dailies_coordinator_headers():
    return TEST_USERS["dailies_coordinator_headers"]


@pytest.fixture
def conform_editor_headers():
    return TEST_USERS["conform_editor_headers"]


@pytest.fixture
def reviewer_lead_headers():
    return TEST_USERS["reviewer_lead_headers"]


@pytest.fixture
def qc_operator_headers():
    return TEST_USERS["qc_operator_headers"]


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def vendor_rep_headers():
    return TEST_USERS["vendor_rep_headers"]


@pytest.fixture
def artist_headers():
    return TEST_USERS["artist_headers"]
