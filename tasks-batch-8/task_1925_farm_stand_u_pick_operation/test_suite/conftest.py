"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def gate_staff_headers():
    return TEST_USERS["gate_staff_headers"]


@pytest.fixture
def field_staff_headers():
    return TEST_USERS["field_staff_headers"]


@pytest.fixture
def kiosk_device_headers():
    return TEST_USERS["kiosk_device_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
