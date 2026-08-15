"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


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
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_headers"]


@pytest.fixture
def thrift_headers():
    return TEST_USERS["thrift_headers"]


@pytest.fixture
def pricing_headers():
    return TEST_USERS["pricing_headers"]
