"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def contact_admin_headers():
    return TEST_USERS["contact_admin_headers"]


@pytest.fixture
def integrator_headers():
    return TEST_USERS["integrator_headers"]


@pytest.fixture
def contact_headers():
    return TEST_USERS["contact_headers"]
