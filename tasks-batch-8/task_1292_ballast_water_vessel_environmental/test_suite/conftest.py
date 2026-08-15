"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def shore_officer_headers():
    return TEST_USERS["shore_officer_headers"]


@pytest.fixture
def vessel_master_headers():
    return TEST_USERS["vessel_master_headers"]


@pytest.fixture
def flag_surveyor_headers():
    return TEST_USERS["flag_surveyor_headers"]


@pytest.fixture
def psc_officer_headers():
    return TEST_USERS["psc_officer_headers"]
