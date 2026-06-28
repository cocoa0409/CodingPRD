"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["intake_clerk_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["fee_analyst_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["runner_dispatcher_headers"]


@pytest.fixture
def lien_officer_headers():
    return TEST_USERS["lien_officer_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]
