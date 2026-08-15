"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def nurse_admin_headers():
    return TEST_USERS["nurse_admin_headers"]


@pytest.fixture
def charge_nurse_headers():
    return TEST_USERS["charge_nurse_headers"]


@pytest.fixture
def staff_nurse_headers():
    return TEST_USERS["staff_nurse_headers"]


@pytest.fixture
def float_coordinator_headers():
    return TEST_USERS["float_coordinator_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
