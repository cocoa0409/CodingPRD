"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restart before every test → empty DB each time).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def patron_headers():
    """Shared Patron headers — for non-ownership tests only (entity_backed role)."""
    return TEST_USERS["patron_headers"]


@pytest.fixture
def librarian_headers():
    return TEST_USERS["librarian_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]
