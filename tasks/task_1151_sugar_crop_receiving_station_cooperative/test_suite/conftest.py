"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def station_operator_headers():
    return TEST_USERS["station_operator_headers"]


@pytest.fixture
def quality_tech_headers():
    return TEST_USERS["quality_tech_headers"]


@pytest.fixture
def pool_accountant_headers():
    return TEST_USERS["pool_accountant_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
