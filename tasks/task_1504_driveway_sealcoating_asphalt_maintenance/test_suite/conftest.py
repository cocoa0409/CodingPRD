"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and API_BASE_URL injection; tests assume the
server is already running and start against an empty database.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def office_admin_headers():
    return TEST_USERS["office_admin_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def crew_lead_headers():
    return TEST_USERS["crew_lead_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
