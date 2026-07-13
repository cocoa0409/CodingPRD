"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (a fresh server + empty database before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def attorney_headers():
    return TEST_USERS["attorney_headers"]


@pytest.fixture
def notary_headers():
    return TEST_USERS["notary_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
