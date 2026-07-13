"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["public_health_admin_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def partner_headers():
    return TEST_USERS["mutual_aid_partner_headers"]


@pytest.fixture
def clinical_headers():
    return TEST_USERS["clinical_lead_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]
