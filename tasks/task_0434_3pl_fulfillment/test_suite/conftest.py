"""Pytest fixtures exposing test_helpers infrastructure for the 3PL fulfillment suite."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def client_user_headers():
    return TEST_USERS["client_user_headers"]


@pytest.fixture
def receiving_clerk_headers():
    return TEST_USERS["receiving_clerk_headers"]


@pytest.fixture
def wave_planner_headers():
    return TEST_USERS["wave_planner_headers"]


@pytest.fixture
def pick_operator_headers():
    return TEST_USERS["pick_operator_headers"]


@pytest.fixture
def pack_station_headers():
    return TEST_USERS["pack_station_headers"]


@pytest.fixture
def ship_station_headers():
    return TEST_USERS["ship_station_headers"]


@pytest.fixture
def returns_clerk_headers():
    return TEST_USERS["returns_clerk_headers"]
