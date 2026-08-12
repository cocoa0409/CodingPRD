"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def design_manager_headers():
    return TEST_USERS["design_manager_headers"]


@pytest.fixture
def permit_coordinator_headers():
    return TEST_USERS["permit_coordinator_headers"]


@pytest.fixture
def procurement_lead_headers():
    return TEST_USERS["procurement_lead_headers"]


@pytest.fixture
def gc_vendor_headers():
    return TEST_USERS["gc_vendor_headers"]


@pytest.fixture
def site_superintendent_headers():
    return TEST_USERS["site_superintendent_headers"]


@pytest.fixture
def operations_lead_headers():
    return TEST_USERS["operations_lead_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]
