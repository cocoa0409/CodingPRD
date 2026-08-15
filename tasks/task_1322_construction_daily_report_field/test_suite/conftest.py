"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def superintendent_headers():
    return TEST_USERS["superintendent_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def contractor_rep_headers():
    return TEST_USERS["contractor_rep_headers"]


@pytest.fixture
def owner_rep_headers():
    return TEST_USERS["owner_rep_headers"]
