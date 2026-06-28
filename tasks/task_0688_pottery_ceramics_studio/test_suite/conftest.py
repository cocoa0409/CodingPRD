"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; conftest only wires fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
