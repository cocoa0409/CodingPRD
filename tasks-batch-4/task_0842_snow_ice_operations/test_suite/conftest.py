"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dispatch_headers():
    return TEST_USERS["dispatch_headers"]


@pytest.fixture
def yard_headers():
    return TEST_USERS["yard_headers"]


@pytest.fixture
def citizen_headers():
    return TEST_USERS["citizen_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]
