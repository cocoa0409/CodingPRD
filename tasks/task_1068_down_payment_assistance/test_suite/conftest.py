"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-per-test) is owned by
prd-bench-local-runner; these fixtures only surface the API client and the
pre-built role headers. The database is empty at the start of every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def closing_coordinator_headers():
    return TEST_USERS["closing_coordinator_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
