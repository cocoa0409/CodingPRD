"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def credit_analyst_headers():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def credit_analyst_2_headers():
    return TEST_USERS["credit_analyst_2_headers"]


@pytest.fixture
def funding_officer_headers():
    return TEST_USERS["funding_officer_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]
