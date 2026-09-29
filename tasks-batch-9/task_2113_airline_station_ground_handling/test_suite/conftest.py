"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def station_manager_headers():
    return TEST_USERS["station_manager_headers"]


@pytest.fixture
def duty_officer_headers():
    return TEST_USERS["duty_officer_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def billing_controller_headers():
    return TEST_USERS["billing_controller_headers"]


@pytest.fixture
def contract_auditor_headers():
    return TEST_USERS["contract_auditor_headers"]


@pytest.fixture
def subcontractor_admin_headers():
    return TEST_USERS["subcontractor_admin_headers"]
