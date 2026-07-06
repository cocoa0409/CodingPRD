"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_clerk_headers():
    return TEST_USERS["intake_clerk_headers"]


@pytest.fixture
def screening_officer_headers():
    return TEST_USERS["screening_officer_headers"]


@pytest.fixture
def assignment_coordinator_headers():
    return TEST_USERS["assignment_coordinator_headers"]


@pytest.fixture
def supervising_attorney_headers():
    return TEST_USERS["supervising_attorney_headers"]


@pytest.fixture
def attorney_headers():
    return TEST_USERS["attorney_headers"]
