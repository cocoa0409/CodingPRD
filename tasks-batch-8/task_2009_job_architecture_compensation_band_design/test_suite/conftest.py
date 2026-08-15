"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def comp_admin_headers():
    return TEST_USERS["comp_admin_headers"]


@pytest.fixture
def comp_analyst_headers():
    return TEST_USERS["comp_analyst_headers"]


@pytest.fixture
def comp_manager_headers():
    return TEST_USERS["comp_manager_headers"]


@pytest.fixture
def hrbp_headers():
    return TEST_USERS["hrbp_headers"]


@pytest.fixture
def finance_partner_headers():
    return TEST_USERS["finance_partner_headers"]


@pytest.fixture
def department_manager_headers():
    return TEST_USERS["department_manager_headers"]
