"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, UNRECOGNIZED_ROLE_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admissions_headers():
    return TEST_USERS["admissions_officer_headers"]


@pytest.fixture
def servicing_headers():
    return TEST_USERS["servicing_officer_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def unrecognized_headers():
    return UNRECOGNIZED_ROLE_HEADERS
