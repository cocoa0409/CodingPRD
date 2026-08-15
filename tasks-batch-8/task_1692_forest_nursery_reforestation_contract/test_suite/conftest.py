"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def nursery_manager_headers():
    return TEST_USERS["nursery_manager_headers"]


@pytest.fixture
def contract_officer_headers():
    return TEST_USERS["contract_officer_headers"]


@pytest.fixture
def field_auditor_headers():
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]
