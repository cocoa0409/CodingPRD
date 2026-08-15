"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def cem_headers():
    return TEST_USERS["cem_headers"]


@pytest.fixture
def cem_alt_headers():
    return TEST_USERS["cem_alt_headers"]


@pytest.fixture
def procurement_officer_headers():
    return TEST_USERS["procurement_officer_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
