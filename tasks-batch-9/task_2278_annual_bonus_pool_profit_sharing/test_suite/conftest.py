"""Pytest fixtures exposing the shared test infrastructure."""

import pytest
from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def hr_headers():
    return TEST_USERS["hr_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]
