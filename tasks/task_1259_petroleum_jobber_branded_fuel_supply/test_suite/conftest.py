"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def pricing_headers():
    return TEST_USERS["pricing_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def credit_headers():
    return TEST_USERS["credit_headers"]


@pytest.fixture
def tax_headers():
    return TEST_USERS["tax_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def dealer_headers():
    return TEST_USERS["dealer_headers"]
