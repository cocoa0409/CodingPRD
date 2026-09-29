"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def env_officer_headers():
    return TEST_USERS["env_officer_headers"]


@pytest.fixture
def energy_headers():
    return TEST_USERS["energy_headers"]


@pytest.fixture
def supplier_headers():
    return TEST_USERS["supplier_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
