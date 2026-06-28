"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_admin_headers, make_compliance_headers,
    make_brand_headers, make_creator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def brand_headers():
    return TEST_USERS["brand_headers"]


@pytest.fixture
def creator_headers():
    return TEST_USERS["creator_headers"]
