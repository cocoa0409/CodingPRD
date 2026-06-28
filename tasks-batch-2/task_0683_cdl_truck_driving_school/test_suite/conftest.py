"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def school_admin_headers():
    return TEST_USERS["school_admin_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]
