"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def evaluator_headers():
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def installer_headers():
    return TEST_USERS["installer_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def lender_headers():
    return TEST_USERS["lender_headers"]


@pytest.fixture
def service_headers():
    return TEST_USERS["service_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]
