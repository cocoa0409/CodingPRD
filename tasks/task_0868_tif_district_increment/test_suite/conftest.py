"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def municipal_admin_headers():
    return TEST_USERS["municipal_admin_headers"]


@pytest.fixture
def municipal_admin_2_headers():
    return TEST_USERS["municipal_admin_2_headers"]


@pytest.fixture
def county_clerk_headers():
    return TEST_USERS["county_clerk_headers"]


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def taxing_body_rep_headers():
    return TEST_USERS["taxing_body_rep_headers"]
