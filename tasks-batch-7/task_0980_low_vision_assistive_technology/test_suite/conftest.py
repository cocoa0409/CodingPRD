"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def vision_specialist_headers():
    return TEST_USERS["vision_specialist_headers"]


@pytest.fixture
def funding_coordinator_headers():
    return TEST_USERS["funding_coordinator_headers"]


@pytest.fixture
def payer_adjudicator_headers():
    return TEST_USERS["payer_adjudicator_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def repair_technician_headers():
    return TEST_USERS["repair_technician_headers"]


@pytest.fixture
def clinic_admin_headers():
    return TEST_USERS["clinic_admin_headers"]
