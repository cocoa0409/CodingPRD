"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and PYTHONPATH; the tests assume
the API is reachable at API_BASE_URL and that the database is empty at
the start of every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def faculty_headers():
    """Shared Faculty headers — only for calls that are not ownership-gated."""
    return TEST_USERS["faculty_headers"]


@pytest.fixture
def student_headers():
    """Shared Student headers — only for calls that are not ownership-gated."""
    return TEST_USERS["student_headers"]
