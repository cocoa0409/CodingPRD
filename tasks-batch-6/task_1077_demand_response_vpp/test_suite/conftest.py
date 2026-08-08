"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANON_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_operator_headers():
    return TEST_USERS["program_operator_headers"]


@pytest.fixture
def second_operator_headers():
    return TEST_USERS["second_operator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def aggregator_headers():
    return TEST_USERS["aggregator_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def anon_headers():
    return ANON_HEADERS
