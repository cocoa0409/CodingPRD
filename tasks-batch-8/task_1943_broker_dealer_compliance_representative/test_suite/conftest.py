"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def principal_a_headers():
    return TEST_USERS["principal_a_headers"]


@pytest.fixture
def principal_b_headers():
    return TEST_USERS["principal_b_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
