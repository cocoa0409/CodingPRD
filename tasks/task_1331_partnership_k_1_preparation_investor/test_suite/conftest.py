"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is restarted before each test."""
    return api_client


@pytest.fixture
def fund_tax_admin_headers():
    return TEST_USERS["fund_tax_admin_headers"]


@pytest.fixture
def tax_preparer_headers():
    return TEST_USERS["tax_preparer_headers"]


@pytest.fixture
def tax_reviewer_headers():
    return TEST_USERS["tax_reviewer_headers"]


@pytest.fixture
def investor_services_rep_headers():
    return TEST_USERS["investor_services_rep_headers"]


@pytest.fixture
def investor_headers():
    return TEST_USERS["investor_headers"]
