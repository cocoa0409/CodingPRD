"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def compliance_creator_headers():
    return TEST_USERS["compliance_creator_headers"]


@pytest.fixture
def compliance_approver_headers():
    return TEST_USERS["compliance_approver_headers"]


@pytest.fixture
def line_supervisor_headers():
    return TEST_USERS["line_supervisor_headers"]


@pytest.fixture
def qc_inspector_headers():
    return TEST_USERS["qc_inspector_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]
