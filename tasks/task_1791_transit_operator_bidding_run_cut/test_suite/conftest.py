"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def scheduling_officer_headers():
    return TEST_USERS["scheduling_officer_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def payroll_clerk_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def union_rep_headers():
    return TEST_USERS["union_rep_headers"]
