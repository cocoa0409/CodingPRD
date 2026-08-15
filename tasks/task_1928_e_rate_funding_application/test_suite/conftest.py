"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def pia_reviewer_headers():
    return TEST_USERS["pia_reviewer_headers"]


@pytest.fixture
def commitment_officer_headers():
    return TEST_USERS["commitment_officer_headers"]


@pytest.fixture
def invoice_processor_headers():
    return TEST_USERS["invoice_processor_headers"]


@pytest.fixture
def appeal_officer_headers():
    return TEST_USERS["appeal_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
