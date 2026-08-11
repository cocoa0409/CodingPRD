"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def financial_officer_headers():
    return TEST_USERS["financial_officer_headers"]


@pytest.fixture
def conservator_headers():
    return TEST_USERS["conservator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
