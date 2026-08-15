"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def planner2_headers():
    return TEST_USERS["planner2_headers"]


@pytest.fixture
def po_headers():
    return TEST_USERS["po_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_headers"]


@pytest.fixture
def qa2_headers():
    return TEST_USERS["qa2_headers"]
