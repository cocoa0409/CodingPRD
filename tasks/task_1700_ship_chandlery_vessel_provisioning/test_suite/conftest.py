"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner: the server is
restarted before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def sales_headers():
    return TEST_USERS["sales_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_headers"]


@pytest.fixture
def customs_headers():
    return TEST_USERS["customs_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_headers"]


@pytest.fixture
def officer_headers():
    """Shared fallback only — ownership-gated calls must use
    make_officer_headers(vessel_call_id) with the real VesselCall.id."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def clerk_headers():
    """Shared fallback only — payments must use make_clerk_headers(agent_id)
    with the real ShipAgent.id."""
    return TEST_USERS["clerk_headers"]
