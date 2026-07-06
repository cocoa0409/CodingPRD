"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clinic_admin_headers():
    return TEST_USERS["clinic_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def prescriber_headers():
    return TEST_USERS["prescriber_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def prior_auth_clerk_headers():
    return TEST_USERS["prior_auth_clerk_headers"]
