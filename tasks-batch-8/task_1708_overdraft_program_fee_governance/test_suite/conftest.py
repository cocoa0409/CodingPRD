"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def teller_1_headers():
    return TEST_USERS["teller_1_headers"]


@pytest.fixture
def teller_2_headers():
    return TEST_USERS["teller_2_headers"]


@pytest.fixture
def supervisor_1_headers():
    return TEST_USERS["supervisor_1_headers"]


@pytest.fixture
def supervisor_2_headers():
    return TEST_USERS["supervisor_2_headers"]


@pytest.fixture
def manager_1_headers():
    return TEST_USERS["manager_1_headers"]


@pytest.fixture
def compliance_1_headers():
    return TEST_USERS["compliance_1_headers"]


@pytest.fixture
def compliance_2_headers():
    return TEST_USERS["compliance_2_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]
