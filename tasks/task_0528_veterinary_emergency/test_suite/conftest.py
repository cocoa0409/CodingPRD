"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def triage_nurse_headers():
    return TEST_USERS["triage_nurse_headers"]


@pytest.fixture
def clinician_dvm_headers():
    return TEST_USERS["clinician_dvm_headers"]


@pytest.fixture
def finance_coordinator_headers():
    return TEST_USERS["finance_coordinator_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
