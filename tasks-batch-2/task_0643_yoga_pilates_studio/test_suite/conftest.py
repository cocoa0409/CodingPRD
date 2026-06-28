"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restart before every test) and PYTHONPATH, so
test_helpers is importable directly and the API client points at API_BASE_URL.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def studio_manager_headers():
    return TEST_USERS["studio_manager_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]
