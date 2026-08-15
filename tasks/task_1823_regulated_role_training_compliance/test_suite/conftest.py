"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle owned by the runner)."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["compliance_admin_headers"]


@pytest.fixture
def hr_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
