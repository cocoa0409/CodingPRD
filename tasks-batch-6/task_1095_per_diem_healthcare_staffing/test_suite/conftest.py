"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` is importable, and restarts the
API server (empty database) before every test.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def billing_agent_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def billing_agent_beta_headers():
    return TEST_USERS["billing_agent_beta_headers"]
