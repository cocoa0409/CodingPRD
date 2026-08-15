"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; the client is a session singleton.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server is already running at API_BASE_URL."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def building_admin_headers():
    return TEST_USERS["building_admin_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]
