"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def trust_admin_headers():
    return TEST_USERS["trust_admin_headers"]


@pytest.fixture
def grantor_headers():
    return TEST_USERS["grantor_headers"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trustee_headers"]


@pytest.fixture
def beneficiary_headers():
    return TEST_USERS["beneficiary_headers"]
