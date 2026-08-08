"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["district_administrator_headers"]


@pytest.fixture
def board_headers():
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def collector_headers():
    return TEST_USERS["tax_collector_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["property_owner_headers"]


@pytest.fixture
def ambassador_headers():
    return TEST_USERS["ambassador_headers"]
