"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and starts/stops the
API server (reachable at API_BASE_URL) before each test against an empty DB.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers.test_users import ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def grant_writer_headers():
    return TEST_USERS["grant_writer_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def agency_officer_headers():
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
