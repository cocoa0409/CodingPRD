"""Pytest fixtures exposing test_helpers infrastructure to the test suite."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def authorizer_headers():
    return TEST_USERS["authorizer_headers"]


@pytest.fixture
def dme_coordinator_headers():
    return TEST_USERS["dme_coordinator_headers"]


@pytest.fixture
def clinic_admin_headers():
    return TEST_USERS["clinic_admin_headers"]
