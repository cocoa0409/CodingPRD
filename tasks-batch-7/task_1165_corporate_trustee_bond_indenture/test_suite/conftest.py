"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def trust_officer_headers():
    return TEST_USERS["trust_officer_headers"]


@pytest.fixture
def trust_officer_2_headers():
    return TEST_USERS["trust_officer_2_headers"]


@pytest.fixture
def trust_manager_headers():
    return TEST_USERS["trust_manager_headers"]


@pytest.fixture
def trust_manager_2_headers():
    return TEST_USERS["trust_manager_2_headers"]


@pytest.fixture
def issuer_headers():
    return TEST_USERS["issuer_headers"]


@pytest.fixture
def issuer_2_headers():
    return TEST_USERS["issuer_2_headers"]


@pytest.fixture
def noteholder_headers():
    return TEST_USERS["noteholder_headers"]
