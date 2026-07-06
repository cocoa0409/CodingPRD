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
def wound_clinician_headers():
    return TEST_USERS["wound_clinician_headers"]


@pytest.fixture
def hyperbaric_tech_headers():
    return TEST_USERS["hyperbaric_tech_headers"]


@pytest.fixture
def payer_liaison_headers():
    return TEST_USERS["payer_liaison_headers"]


@pytest.fixture
def attending_physician_headers():
    return TEST_USERS["attending_physician_headers"]
