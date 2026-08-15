"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def gift_officer_headers():
    return TEST_USERS["gift_officer_headers"]


@pytest.fixture
def gift_admin_headers():
    return TEST_USERS["gift_admin_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def estate_manager_headers():
    return TEST_USERS["estate_manager_headers"]


@pytest.fixture
def finance_steward_headers():
    return TEST_USERS["finance_steward_headers"]
