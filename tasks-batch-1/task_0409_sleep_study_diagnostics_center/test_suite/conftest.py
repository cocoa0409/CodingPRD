"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["scheduling_coordinator_headers"]


@pytest.fixture
def technologist_headers():
    return TEST_USERS["sleep_technologist_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def dme_coordinator_headers():
    return TEST_USERS["dme_coordinator_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
