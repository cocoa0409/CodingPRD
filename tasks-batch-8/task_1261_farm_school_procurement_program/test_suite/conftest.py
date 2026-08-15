"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def claims_headers():
    return TEST_USERS["claims_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def kitchen_manager_headers():
    return TEST_USERS["kitchen_manager_headers"]
