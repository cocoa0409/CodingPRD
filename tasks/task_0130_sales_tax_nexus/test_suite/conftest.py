"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restart before every test, empty DB each time).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def preparer_headers():
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
