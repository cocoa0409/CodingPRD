"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def energy_manager_headers():
    return TEST_USERS["energy_manager_headers"]


@pytest.fixture
def energy_analyst_headers():
    return TEST_USERS["energy_analyst_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def food_safety_officer_headers():
    return TEST_USERS["food_safety_officer_headers"]


@pytest.fixture
def maintenance_tech_headers():
    return TEST_USERS["maintenance_tech_headers"]


@pytest.fixture
def bms_gateway_headers():
    return TEST_USERS["bms_gateway_headers"]
