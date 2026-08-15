"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def de_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def sl_headers():
    return TEST_USERS["shop_lead_headers"]


@pytest.fixture
def tt_headers():
    return TEST_USERS["test_technician_headers"]


@pytest.fixture
def ce_headers():
    return TEST_USERS["controls_engineer_headers"]


@pytest.fixture
def fe_headers():
    return TEST_USERS["field_engineer_headers"]


@pytest.fixture
def shipping_headers():
    return TEST_USERS["shipping_clerk_headers"]
