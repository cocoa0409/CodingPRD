"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def railroad_contracts_manager_headers():
    return TEST_USERS["railroad_contracts_manager_headers"]


@pytest.fixture
def shipper_facility_manager_headers():
    # Party-bound to the canonical agreement's shipper_user_id ("shipper-user-1").
    return TEST_USERS["shipper_facility_manager_headers"]


@pytest.fixture
def railroad_engineer_headers():
    return TEST_USERS["railroad_engineer_headers"]


@pytest.fixture
def safety_inspector_headers():
    return TEST_USERS["safety_inspector_headers"]


@pytest.fixture
def railroad_service_manager_headers():
    return TEST_USERS["railroad_service_manager_headers"]
