"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def enrollment_manager_headers():
    return TEST_USERS["enrollment_manager_headers"]


@pytest.fixture
def admissions_officer_headers():
    return TEST_USERS["admissions_officer_headers"]


@pytest.fixture
def financial_aid_officer_headers():
    return TEST_USERS["financial_aid_officer_headers"]


@pytest.fixture
def application_reader_headers():
    # Shared fallback: only safe for tests that do not exercise reviewer
    # identity pinning (submit requires X-User-ID == review.reader_id).
    return TEST_USERS["application_reader_headers"]


@pytest.fixture
def applicant_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["applicant_headers"]
