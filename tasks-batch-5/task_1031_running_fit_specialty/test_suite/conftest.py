"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so test_helpers is importable and
injects API_BASE_URL; it also restarts the server before each test, so every
test begins against an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sm():
    """StoreManager headers — the superset operator, exempt from ownership checks."""
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def anon():
    return TEST_USERS["anonymous_headers"]
