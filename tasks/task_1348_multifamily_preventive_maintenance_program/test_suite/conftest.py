"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_property_manager_headers, make_technician_headers, make_auditor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
