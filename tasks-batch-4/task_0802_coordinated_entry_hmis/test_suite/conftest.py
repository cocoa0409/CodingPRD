"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def shelter_manager_headers():
    return TEST_USERS["shelter_manager_headers"]


@pytest.fixture
def navigator_headers():
    return TEST_USERS["navigator_headers"]


@pytest.fixture
def hmis_admin_headers():
    return TEST_USERS["hmis_admin_headers"]
