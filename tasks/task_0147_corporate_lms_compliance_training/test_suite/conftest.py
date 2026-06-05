"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets API_BASE_URL and PYTHONPATH; test_helpers is importable directly.
The server is restarted before every test, so each test starts against an empty DB.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def learner_headers():
    return TEST_USERS["learner_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]
