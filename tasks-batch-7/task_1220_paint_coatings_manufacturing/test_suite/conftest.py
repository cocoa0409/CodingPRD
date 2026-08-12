"""Pytest fixtures exposing the coatings test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle belongs to the runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def plant_manager_2_headers():
    return TEST_USERS["plant_manager_2_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def production_operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def qc_inspector_headers():
    return TEST_USERS["qc_inspector_headers"]


@pytest.fixture
def qc_inspector_2_headers():
    return TEST_USERS["qc_inspector_2_headers"]


@pytest.fixture
def regulatory_clerk_headers():
    return TEST_USERS["regulatory_clerk_headers"]


@pytest.fixture
def dealer_headers():
    """Shared Dealer constant — only for calls that touch no ownership check."""
    return TEST_USERS["dealer_headers"]
