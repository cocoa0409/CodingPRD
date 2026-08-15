"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def terminal_operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def terminal_operator_scale_headers():
    return TEST_USERS["terminal_operator_scale_headers"]


@pytest.fixture
def wash_operator_headers():
    return TEST_USERS["wash_operator_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def driver_headers():
    # Fallback only — ownership-gated calls must use make_driver_headers(entity_id).
    return TEST_USERS["driver_headers"]


@pytest.fixture
def customer_rep_headers():
    # Fallback only — ownership-gated calls must use make_customer_rep_headers(entity_id).
    return TEST_USERS["customer_rep_headers"]
