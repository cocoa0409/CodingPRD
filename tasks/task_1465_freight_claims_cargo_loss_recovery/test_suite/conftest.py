"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def adjuster2_headers():
    return TEST_USERS["adjuster2_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager2_headers():
    return TEST_USERS["manager2_headers"]


@pytest.fixture
def salvage_headers():
    return TEST_USERS["salvage_headers"]


@pytest.fixture
def subro_headers():
    return TEST_USERS["subro_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]
