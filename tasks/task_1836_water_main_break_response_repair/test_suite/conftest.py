"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def crew_lead_headers():
    return TEST_USERS["crew_lead_headers"]


@pytest.fixture
def wq_officer_headers():
    return TEST_USERS["wq_officer_headers"]


@pytest.fixture
def wq_officer_2_headers():
    return TEST_USERS["wq_officer_2_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]
