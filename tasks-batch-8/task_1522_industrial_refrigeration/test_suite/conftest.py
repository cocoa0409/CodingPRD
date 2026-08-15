"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def ps_coordinator_headers():
    return TEST_USERS["ps_coordinator_headers"]


@pytest.fixture
def maintenance_lead_headers():
    return TEST_USERS["maintenance_lead_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def contractor_rep_headers():
    return TEST_USERS["contractor_rep_headers"]
