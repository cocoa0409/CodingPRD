"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def bursar_headers():
    return TEST_USERS["bursar_headers"]


@pytest.fixture
def library_headers():
    return TEST_USERS["library_headers"]


@pytest.fixture
def archive_headers():
    return TEST_USERS["archive_headers"]


@pytest.fixture
def requester_headers():
    return TEST_USERS["requester_headers"]
