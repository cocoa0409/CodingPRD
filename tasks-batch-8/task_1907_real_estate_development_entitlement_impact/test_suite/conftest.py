"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def applicant_headers():
    """Shared Applicant fallback — only for tests that never exercise
    ownership (entity-backed role; prefer make_applicant_headers(id))."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def staff_reviewer_headers():
    """Shared StaffReviewer fallback — non-authorship tests only."""
    return TEST_USERS["staff_reviewer_headers"]


@pytest.fixture
def decision_authority_headers():
    """Shared DecisionAuthority fallback — non-gated tests only."""
    return TEST_USERS["decision_authority_headers"]
