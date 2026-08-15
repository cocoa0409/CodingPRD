"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def requester_headers():
    return TEST_USERS["requester_headers"]


@pytest.fixture
def requester2_headers():
    return TEST_USERS["requester2_headers"]


@pytest.fixture
def department_approver_headers():
    return TEST_USERS["department_approver_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def contract_officer_headers():
    return TEST_USERS["contract_officer_headers"]


@pytest.fixture
def grant_officer_headers():
    return TEST_USERS["grant_officer_headers"]


@pytest.fixture
def ap_clerk_headers():
    return TEST_USERS["ap_clerk_headers"]


@pytest.fixture
def receiving_clerk_headers():
    return TEST_USERS["receiving_clerk_headers"]


@pytest.fixture
def surplus_manager_headers():
    return TEST_USERS["surplus_manager_headers"]


@pytest.fixture
def cardholder_headers():
    return TEST_USERS["cardholder_headers"]
