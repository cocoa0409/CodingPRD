"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]
