"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_officer_headers():
    return TEST_USERS["program_officer_headers"]


@pytest.fixture
def grants_manager_headers():
    return TEST_USERS["grants_manager_headers"]


@pytest.fixture
def panelist_headers():
    return TEST_USERS["panelist_headers"]


@pytest.fixture
def subrecipient_headers():
    return TEST_USERS["subrecipient_headers"]
