"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def grower_headers():
    return TEST_USERS["grower_headers"]


@pytest.fixture
def service_tech_headers():
    return TEST_USERS["service_tech_headers"]


@pytest.fixture
def livehaul_headers():
    return TEST_USERS["livehaul_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]
