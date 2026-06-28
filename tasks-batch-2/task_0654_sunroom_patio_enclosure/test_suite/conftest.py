"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def homeowner_headers():
    return TEST_USERS["homeowner_headers"]


@pytest.fixture
def sales_designer_headers():
    return TEST_USERS["sales_designer_headers"]


@pytest.fixture
def permit_officer_headers():
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def manufacturer_headers():
    return TEST_USERS["manufacturer_headers"]


@pytest.fixture
def install_manager_headers():
    return TEST_USERS["install_manager_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]
