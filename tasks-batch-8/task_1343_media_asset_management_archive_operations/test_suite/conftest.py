"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def ingest_coordinator_headers():
    return TEST_USERS["ingest_coordinator_headers"]


@pytest.fixture
def metadata_cataloger_headers():
    return TEST_USERS["metadata_cataloger_headers"]


@pytest.fixture
def metadata_librarian_headers():
    return TEST_USERS["metadata_librarian_headers"]


@pytest.fixture
def archivist_lead_headers():
    return TEST_USERS["archivist_lead_headers"]


@pytest.fixture
def rights_manager_headers():
    return TEST_USERS["rights_manager_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def access_officer_headers():
    return TEST_USERS["access_officer_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]
