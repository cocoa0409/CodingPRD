"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def taxpayer_headers():
    return TEST_USERS["taxpayer_headers"]


@pytest.fixture
def preparer_headers():
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def irs_gateway_headers():
    return TEST_USERS["irs_gateway_headers"]
