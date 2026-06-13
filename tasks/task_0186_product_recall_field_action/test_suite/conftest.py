"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` imports without sys.path hacks,
and manages server lifecycle (restarted before every test → empty DB per test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def recall_coordinator_headers():
    return TEST_USERS["recall_coordinator_headers"]


@pytest.fixture
def quality_officer_headers():
    return TEST_USERS["quality_officer_headers"]


@pytest.fixture
def field_service_agent_headers():
    return TEST_USERS["field_service_agent_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
