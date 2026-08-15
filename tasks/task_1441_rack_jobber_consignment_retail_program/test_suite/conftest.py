"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def jobber_admin_headers():
    return TEST_USERS["jobber_admin_headers"]


@pytest.fixture
def retailer_manager_headers():
    return TEST_USERS["retailer_manager_headers"]


@pytest.fixture
def route_driver_headers():
    return TEST_USERS["route_driver_headers"]


@pytest.fixture
def field_auditor_headers():
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture
def jobber_finance_headers():
    return TEST_USERS["jobber_finance_headers"]
