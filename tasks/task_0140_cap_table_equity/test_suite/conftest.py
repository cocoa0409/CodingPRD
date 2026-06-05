"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, sets API_BASE_URL,
and restarts the server (empty DB) before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def administrator_headers():
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def board_approver_headers():
    return TEST_USERS["board_approver_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def stakeholder_headers():
    return TEST_USERS["stakeholder_headers"]
