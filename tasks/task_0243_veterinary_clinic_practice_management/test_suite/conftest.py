"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so `test_helpers` is importable, and owns the
server lifecycle (restart before every test). This file just wires up fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def receptionist_headers():
    return TEST_USERS["receptionist_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def practice_manager_headers():
    return TEST_USERS["practice_manager_headers"]
