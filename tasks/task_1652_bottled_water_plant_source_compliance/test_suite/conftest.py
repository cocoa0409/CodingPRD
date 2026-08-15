"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def source_monitor_headers():
    return TEST_USERS["source_monitor_headers"]


@pytest.fixture
def qa_officer_headers():
    return TEST_USERS["qa_officer_headers"]


@pytest.fixture
def production_lead_headers():
    return TEST_USERS["production_lead_headers"]


@pytest.fixture
def sanitation_lead_headers():
    return TEST_USERS["sanitation_lead_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
