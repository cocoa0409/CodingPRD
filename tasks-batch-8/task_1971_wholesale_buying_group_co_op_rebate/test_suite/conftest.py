"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and injects API_BASE_URL; the
server is restarted before every test, so each test starts against an
empty database and builds its own preconditions.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["coop_admin_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["program_auditor_headers"]


@pytest.fixture
def member_rep_headers():
    return TEST_USERS["member_rep_headers"]


@pytest.fixture
def supplier_rep_headers():
    return TEST_USERS["supplier_rep_headers"]
