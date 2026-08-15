"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def ic_member_headers():
    return TEST_USERS["ic_member_headers"]


@pytest.fixture
def ic_member_2_headers():
    return TEST_USERS["ic_member_2_headers"]


@pytest.fixture
def ic_chair_headers():
    return TEST_USERS["ic_chair_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
