"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["regulatory_admin_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["cycle_operator_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["dosimetry_analyst_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["quality_release_officer_headers"]
