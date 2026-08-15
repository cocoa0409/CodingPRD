"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; these tests
assume the server is already running and freshly restarted (empty database)
before every test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def borrower_headers():
    """Shared Borrower identity — only for tests that do not exercise ownership."""
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def board_headers():
    return TEST_USERS["board_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]
