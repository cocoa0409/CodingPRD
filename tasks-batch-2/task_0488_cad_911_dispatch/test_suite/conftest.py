"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def calltaker_headers():
    return TEST_USERS["calltaker_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def field_unit_headers():
    return TEST_USERS["field_unit_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def records_headers():
    return TEST_USERS["records_headers"]


@pytest.fixture
def system_clock_headers():
    return TEST_USERS["system_clock_headers"]
