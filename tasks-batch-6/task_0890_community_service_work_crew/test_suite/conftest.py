"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so ``test_helpers`` is importable, and manages server
lifecycle (restarting via start.sh before each test), so conftest only wires fixtures.
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
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator2_headers():
    return TEST_USERS["coordinator2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
