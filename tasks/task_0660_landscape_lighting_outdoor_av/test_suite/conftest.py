"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def designer_headers():
    return TEST_USERS["lighting_designer_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["install_tech_headers"]


@pytest.fixture
def programmer_headers():
    return TEST_USERS["control_programmer_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["operations_admin_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
