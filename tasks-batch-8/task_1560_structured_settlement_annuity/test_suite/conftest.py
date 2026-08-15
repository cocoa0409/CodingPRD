"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def operations_specialist_headers():
    return TEST_USERS["operations_specialist_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def judicial_recorder_headers():
    return TEST_USERS["judicial_recorder_headers"]


@pytest.fixture
def reader_headers():
    return TEST_USERS["reader_headers"]


@pytest.fixture
def payee_headers():
    return TEST_USERS["payee_headers"]
