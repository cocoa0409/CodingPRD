"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
    make_owner_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return make_firm_admin_headers()


@pytest.fixture
def architect_headers():
    return make_architect_headers()


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
