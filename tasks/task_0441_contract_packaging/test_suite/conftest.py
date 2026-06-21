"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restart before each test). Tests assume an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, UNKNOWN_ROLE_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def receiver_headers():
    return TEST_USERS["receiver_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def qa_inspector_headers():
    return TEST_USERS["qa_inspector_headers"]


@pytest.fixture
def unknown_role_headers():
    return UNKNOWN_ROLE_HEADERS
