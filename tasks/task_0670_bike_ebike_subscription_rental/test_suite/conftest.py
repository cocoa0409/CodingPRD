"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_ops_admin_headers, make_field_tech_headers, make_anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return make_ops_admin_headers()


@pytest.fixture
def field_tech_headers():
    return make_field_tech_headers()


@pytest.fixture
def anonymous_headers():
    return make_anonymous_headers()


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]
