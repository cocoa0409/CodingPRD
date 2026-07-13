"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle, PYTHONPATH, and API_BASE_URL are owned by prd-bench-local-runner.
The server is restarted (empty DB, clock at the startup default) before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def attendant_headers():
    return TEST_USERS["attendant_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]
