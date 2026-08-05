"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def meter_tech_headers():
    return TEST_USERS["meter_tech_headers"]


@pytest.fixture
def collections_officer_headers():
    return TEST_USERS["collections_officer_headers"]


@pytest.fixture
def assistance_caseworker_headers():
    return TEST_USERS["assistance_caseworker_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
