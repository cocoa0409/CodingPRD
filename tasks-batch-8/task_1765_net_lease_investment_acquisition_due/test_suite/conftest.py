"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def dd_officer_headers():
    return TEST_USERS["dd_officer_headers"]


@pytest.fixture
def capital_markets_headers():
    return TEST_USERS["capital_markets_headers"]


@pytest.fixture
def escrow_headers():
    return TEST_USERS["escrow_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
