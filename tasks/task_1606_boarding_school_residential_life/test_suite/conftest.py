"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]


@pytest.fixture
def dorm_parent_headers():
    return TEST_USERS["dorm_parent_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def dean_headers():
    return TEST_USERS["dean_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]
