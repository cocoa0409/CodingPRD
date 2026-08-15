"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def sales_consultant_headers():
    return TEST_USERS["sales_consultant_headers"]


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]


@pytest.fixture
def service_advisor_headers():
    return TEST_USERS["service_advisor_headers"]


@pytest.fixture
def parts_counter_rep_headers():
    return TEST_USERS["parts_counter_rep_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def oem_adjudicator_headers():
    return TEST_USERS["oem_adjudicator_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]
