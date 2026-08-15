"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def housing_coordinator_headers():
    return TEST_USERS["housing_coordinator_headers"]


@pytest.fixture
def employment_specialist_headers():
    return TEST_USERS["employment_specialist_headers"]


@pytest.fixture
def agency_director_headers():
    return TEST_USERS["agency_director_headers"]


@pytest.fixture
def federal_officer_headers():
    return TEST_USERS["federal_officer_headers"]
