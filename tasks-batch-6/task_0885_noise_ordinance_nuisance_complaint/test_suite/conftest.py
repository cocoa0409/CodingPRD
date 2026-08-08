"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def code_officer_headers():
    return TEST_USERS["code_officer_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def permit_clerk_headers():
    return TEST_USERS["permit_clerk_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
