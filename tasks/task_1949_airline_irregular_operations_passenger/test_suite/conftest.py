"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is
restarted before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_passenger_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_controller_headers():
    return TEST_USERS["ops_controller_headers"]


@pytest.fixture
def duty_manager_headers():
    return TEST_USERS["duty_manager_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def crew_scheduler_headers():
    return TEST_USERS["crew_scheduler_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def passenger_headers_factory():
    """Factory fixture: make_passenger_headers(passenger_id) for the
    entity-backed Passenger role (PRD §2.1)."""
    return make_passenger_headers
