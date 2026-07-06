"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def studio_ops_headers():
    return TEST_USERS["studio_ops_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def billing_ops_headers():
    return TEST_USERS["billing_ops_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
