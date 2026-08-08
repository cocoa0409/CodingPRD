"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def zoningboard_headers():
    return TEST_USERS["zoningboard_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
