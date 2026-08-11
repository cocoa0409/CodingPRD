"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def surveyor_headers():
    return TEST_USERS["surveyor_headers"]


@pytest.fixture
def monitor_headers():
    return TEST_USERS["monitor_headers"]


@pytest.fixture
def site_operator_headers():
    return TEST_USERS["site_operator_headers"]
