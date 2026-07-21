"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def tpa_admin_headers():
    return TEST_USERS["tpa_admin_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def fund_manager_headers():
    return TEST_USERS["fund_manager_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
