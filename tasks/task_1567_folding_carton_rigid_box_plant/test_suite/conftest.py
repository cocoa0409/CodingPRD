"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def structural_designer_headers():
    return TEST_USERS["structural_designer_headers"]


@pytest.fixture
def press_operator_headers():
    return TEST_USERS["press_operator_headers"]


@pytest.fixture
def finishing_operator_headers():
    return TEST_USERS["finishing_operator_headers"]


@pytest.fixture
def kitting_lead_headers():
    return TEST_USERS["kitting_lead_headers"]


@pytest.fixture
def brand_quality_headers():
    return TEST_USERS["brand_quality_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]
