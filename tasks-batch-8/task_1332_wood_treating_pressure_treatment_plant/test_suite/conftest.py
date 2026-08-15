"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def plant_operator_headers():
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def accounts_receivable_headers():
    return TEST_USERS["accounts_receivable_headers"]
