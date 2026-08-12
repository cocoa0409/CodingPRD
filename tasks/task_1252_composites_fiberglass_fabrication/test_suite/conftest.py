"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def tooling_engineer_headers():
    return TEST_USERS["tooling_engineer_headers"]


@pytest.fixture
def laminator_headers():
    return TEST_USERS["laminator_headers"]


@pytest.fixture
def cure_technician_headers():
    return TEST_USERS["cure_technician_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def ehs_officer_headers():
    return TEST_USERS["ehs_officer_headers"]
