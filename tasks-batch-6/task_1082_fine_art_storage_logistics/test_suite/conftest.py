"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
