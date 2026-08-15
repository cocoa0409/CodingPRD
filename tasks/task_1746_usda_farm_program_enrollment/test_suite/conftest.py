"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def county_specialist_headers():
    return TEST_USERS["county_specialist_headers"]


@pytest.fixture
def county_executive_director_headers():
    return TEST_USERS["county_executive_director_headers"]


@pytest.fixture
def county_committee_headers():
    return TEST_USERS["county_committee_headers"]
