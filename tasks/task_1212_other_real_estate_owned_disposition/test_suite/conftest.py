"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def oreo_admin_headers():
    return TEST_USERS["oreo_admin_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def oreo_specialist_headers():
    return TEST_USERS["oreo_specialist_headers"]


@pytest.fixture
def chief_appraiser_headers():
    return TEST_USERS["chief_appraiser_headers"]


@pytest.fixture
def credit_officer_headers():
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def oreo_committee_headers():
    return TEST_USERS["oreo_committee_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
