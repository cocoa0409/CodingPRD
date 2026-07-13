"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["forestry_admin_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["forestry_staff_headers"]


@pytest.fixture
def arborist_headers():
    return TEST_USERS["arborist_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]
