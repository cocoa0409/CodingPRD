"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["dispatch_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def corporate_booker_headers():
    return TEST_USERS["corporate_booker_headers"]


@pytest.fixture
def affiliate_partner_headers():
    return TEST_USERS["affiliate_partner_headers"]


@pytest.fixture
def chauffeur_headers():
    return TEST_USERS["chauffeur_headers"]
