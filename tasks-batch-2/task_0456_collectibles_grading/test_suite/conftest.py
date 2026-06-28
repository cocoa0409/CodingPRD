"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def receiver_headers():
    return TEST_USERS["receiver_headers"]


@pytest.fixture
def grader_headers():
    return TEST_USERS["grader_headers"]


@pytest.fixture
def authenticator_headers():
    return TEST_USERS["authenticator_headers"]


@pytest.fixture
def lab_admin_headers():
    return TEST_USERS["lab_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
