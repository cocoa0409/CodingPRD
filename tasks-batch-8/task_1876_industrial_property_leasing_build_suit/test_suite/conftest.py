"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def tenant_rep_1_headers():
    return TEST_USERS["tenant_rep_1_headers"]


@pytest.fixture
def tenant_rep_2_headers():
    return TEST_USERS["tenant_rep_2_headers"]


@pytest.fixture
def leasing_manager_headers():
    return TEST_USERS["leasing_manager_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
