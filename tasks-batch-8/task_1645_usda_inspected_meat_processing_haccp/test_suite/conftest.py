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
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def qa_tech_headers():
    return TEST_USERS["qa_tech_headers"]


@pytest.fixture
def lab_analyst_headers():
    return TEST_USERS["lab_analyst_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]
