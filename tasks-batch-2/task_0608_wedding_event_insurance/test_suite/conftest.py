"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and the server lifecycle.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]
