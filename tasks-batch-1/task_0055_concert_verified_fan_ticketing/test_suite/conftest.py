"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def promoter_headers():
    return TEST_USERS["promoter_headers"]


@pytest.fixture
def scanner_headers():
    return TEST_USERS["scanner_headers"]


@pytest.fixture
def fan_headers():
    return TEST_USERS["fan_headers"]
