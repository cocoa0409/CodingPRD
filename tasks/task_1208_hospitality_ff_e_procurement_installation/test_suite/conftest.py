"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project root
to PYTHONPATH before invoking pytest, so test_helpers imports cleanly. Server
lifecycle is the runner's job; each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def purchasing_agent_headers():
    return TEST_USERS["purchasing_agent_headers"]


@pytest.fixture
def brand_approver_headers():
    return TEST_USERS["brand_approver_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def warehouse_receiver_headers():
    return TEST_USERS["warehouse_receiver_headers"]


@pytest.fixture
def installation_manager_headers():
    return TEST_USERS["installation_manager_headers"]


@pytest.fixture
def owner_rep_headers():
    return TEST_USERS["owner_rep_headers"]
