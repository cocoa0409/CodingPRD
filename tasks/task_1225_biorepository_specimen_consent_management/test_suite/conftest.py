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
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def researcher_headers():
    return TEST_USERS["researcher_headers"]


@pytest.fixture
def quality_officer_headers():
    return TEST_USERS["quality_officer_headers"]
