"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is restarted
before every test, so each test starts against an empty database with the
logical clock at its startup default.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def engineer_of_record_headers():
    return TEST_USERS["engineer_of_record_headers"]


@pytest.fixture
def lab_analyst_headers():
    return TEST_USERS["lab_analyst_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def building_official_headers():
    return TEST_USERS["building_official_headers"]
