"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def production_admin_headers():
    return TEST_USERS["production_admin_headers"]


@pytest.fixture
def production_admin_2_headers():
    return TEST_USERS["production_admin_2_headers"]


@pytest.fixture
def casting_director_headers():
    return TEST_USERS["casting_director_headers"]


@pytest.fixture
def casting_director_2_headers():
    return TEST_USERS["casting_director_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def business_affairs_headers():
    return TEST_USERS["business_affairs_headers"]


@pytest.fixture
def business_affairs_2_headers():
    return TEST_USERS["business_affairs_2_headers"]


@pytest.fixture
def welfare_officer_headers():
    return TEST_USERS["welfare_officer_headers"]


@pytest.fixture
def welfare_officer_2_headers():
    return TEST_USERS["welfare_officer_2_headers"]


@pytest.fixture
def applicant_headers():
    """Participant headers for calls that are NOT ownership-gated."""
    return TEST_USERS["applicant_headers"]
