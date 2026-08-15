"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def ops_officer_headers():
    return TEST_USERS["ops_officer_headers"]


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
