"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages server lifecycle (restarting the server with
an empty database before each test) and sets PYTHONPATH so ``test_helpers`` is
importable.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def specialist_headers():
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def toxicologist_headers():
    return TEST_USERS["toxicologist_headers"]


@pytest.fixture
def surveillance_headers():
    return TEST_USERS["surveillance_officer_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["system_admin_headers"]
