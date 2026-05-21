"""Pytest fixtures exposing test_helpers infrastructure for SNAP/EBT tests."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def caseworker2_headers():
    return TEST_USERS["caseworker2_headers"]


@pytest.fixture
def household_head_headers():
    return TEST_USERS["household_head_headers"]


@pytest.fixture
def household_head2_headers():
    return TEST_USERS["household_head2_headers"]


@pytest.fixture
def merchant_headers():
    return TEST_USERS["merchant_headers"]


@pytest.fixture
def fraud_investigator_headers():
    return TEST_USERS["fraud_investigator_headers"]


@pytest.fixture
def fraud_investigator2_headers():
    return TEST_USERS["fraud_investigator2_headers"]


@pytest.fixture
def state_admin_headers():
    return TEST_USERS["state_admin_headers"]


@pytest.fixture
def state_admin2_headers():
    return TEST_USERS["state_admin2_headers"]


@pytest.fixture
def system_test_headers():
    return TEST_USERS["system_test_headers"]
