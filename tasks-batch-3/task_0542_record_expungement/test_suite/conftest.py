"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restarted before every test) and PYTHONPATH,
so ``test_helpers`` is importable directly.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def agency_headers():
    return TEST_USERS["agency_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def petitioner_headers():
    return TEST_USERS["petitioner_headers"]
