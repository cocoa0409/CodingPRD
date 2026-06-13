"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable. The API client is
session-scoped (server lifecycle is owned by prd-bench-local-runner); role
headers are simple per-call fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def bookkeeper_headers():
    return TEST_USERS["bookkeeper_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
