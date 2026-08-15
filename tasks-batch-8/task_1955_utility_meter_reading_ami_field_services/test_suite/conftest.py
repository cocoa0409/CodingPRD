"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, API_BASE_URL, PYTHONPATH) is owned by the
prd-bench-local-runner framework; the tests assume the server is reachable.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def meter_ops_admin_headers():
    return TEST_USERS["meter_ops_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def billing_liaison_headers():
    return TEST_USERS["billing_liaison_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]
