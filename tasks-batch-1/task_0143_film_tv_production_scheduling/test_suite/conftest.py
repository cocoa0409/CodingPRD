"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def line_producer_headers():
    return TEST_USERS["line_producer_headers"]


@pytest.fixture
def first_ad_headers():
    return TEST_USERS["first_ad_headers"]


@pytest.fixture
def payroll_coordinator_headers():
    return TEST_USERS["payroll_coordinator_headers"]


@pytest.fixture
def post_supervisor_headers():
    return TEST_USERS["post_supervisor_headers"]


@pytest.fixture
def union_rep_headers():
    return TEST_USERS["union_rep_headers"]
