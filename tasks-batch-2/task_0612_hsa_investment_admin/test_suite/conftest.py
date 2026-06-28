"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restart before every test) and PYTHONPATH, so
test_helpers is importable directly and every test starts against an empty database.
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
def admin_b_headers():
    return TEST_USERS["admin_b_headers"]


@pytest.fixture
def accountholder_headers():
    return TEST_USERS["accountholder_headers"]


@pytest.fixture
def employer_headers():
    return TEST_USERS["employer_headers"]
