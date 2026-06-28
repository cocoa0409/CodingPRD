"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires up
fixtures. Field-data isolation is guaranteed by the harness (the server is
restarted against an empty database before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]
