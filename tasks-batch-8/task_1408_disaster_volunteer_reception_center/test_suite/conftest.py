"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def vetting_headers():
    return TEST_USERS["vetting_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def risk_headers():
    return TEST_USERS["risk_headers"]


@pytest.fixture
def agency_headers():
    return TEST_USERS["agency_headers"]
