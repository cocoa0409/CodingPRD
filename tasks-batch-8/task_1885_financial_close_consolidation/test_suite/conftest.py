"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def preparer_headers():
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
