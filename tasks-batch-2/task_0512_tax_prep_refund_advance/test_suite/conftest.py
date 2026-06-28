"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, readiness, per-test restart) is owned by
prd-bench-local-runner; conftest only wires up fixtures. The runner sets
PYTHONPATH so test_helpers is importable directly.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def office_manager_headers():
    return TEST_USERS["office_manager_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def tax_preparer_headers():
    return TEST_USERS["tax_preparer_headers"]


@pytest.fixture
def bank_officer_headers():
    return TEST_USERS["bank_officer_headers"]
