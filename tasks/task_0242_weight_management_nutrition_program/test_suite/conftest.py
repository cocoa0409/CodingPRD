"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so ``test_helpers`` is importable, and starts /
restarts the server before each test. These fixtures never touch server
lifecycle — they only hand tests a ready API client and pre-built role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def billing_agent_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
