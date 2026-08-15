"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and API_BASE_URL injection; the client below
is a thin adapter over the already-running server.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def caseworker2_headers():
    return TEST_USERS["caseworker2_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
