"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and the server
lifecycle (restart with empty DB + reset clock before each test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def settlement_admin_headers():
    return TEST_USERS["settlement_admin_headers"]


@pytest.fixture
def fund_controller_headers():
    return TEST_USERS["fund_controller_headers"]


@pytest.fixture
def claims_reviewer_headers():
    return TEST_USERS["claims_reviewer_headers"]


@pytest.fixture
def claims_administrator_headers():
    return TEST_USERS["claims_administrator_headers"]


@pytest.fixture
def court_headers():
    return TEST_USERS["court_headers"]


@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]
