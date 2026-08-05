"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; these fixtures only expose
the shared API client and pre-built role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def host_headers():
    return TEST_USERS["host_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
