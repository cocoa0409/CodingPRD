"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the harness; tests assume the API is reachable
at API_BASE_URL and the database is empty at the start of every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def ram_headers():
    return TEST_USERS["ram_headers"]


@pytest.fixture
def board_reporter_headers():
    return TEST_USERS["board_reporter_headers"]


@pytest.fixture
def remediation_owner_headers():
    return TEST_USERS["remediation_owner_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]
