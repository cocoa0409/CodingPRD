"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def vetting_officer_headers():
    return TEST_USERS["vetting_officer_headers"]


@pytest.fixture
def enrollment_officer_headers():
    return TEST_USERS["enrollment_officer_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def scheduling_admin_headers():
    return TEST_USERS["scheduling_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
