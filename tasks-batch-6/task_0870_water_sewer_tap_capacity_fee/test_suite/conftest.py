"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def applicant2_headers():
    return TEST_USERS["applicant2_headers"]


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer2_headers():
    return TEST_USERS["reviewer2_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def field_inspector_headers():
    return TEST_USERS["field_inspector_headers"]
