"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every pytest test, so every test
begins against an empty database. Each test pins the clock as needed and
constructs its own preconditions through the helpers in test_helpers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def lo_headers():
    """LoanOfficer headers (opaque role, X-User-ID = 'lo-001')."""
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def lo_alt_headers():
    """Second LoanOfficer X-User-ID — used to break SoD ties."""
    return TEST_USERS["loan_officer_alt_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter_alt_headers():
    return TEST_USERS["underwriter_alt_headers"]


@pytest.fixture
def closer_headers():
    return TEST_USERS["closer_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def title_agent_headers():
    return TEST_USERS["title_agent_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def applicant_fallback_headers():
    """Applicant headers with a placeholder X-User-ID.

    Only safe for non-ownership tests (e.g., reads of resources that do not
    require the X-User-ID to equal the resource's applicant_id). For
    POST /disclosures/{id}/acknowledge, use make_applicant_headers(applicant_id)
    directly with the real Applicant.id.
    """
    return TEST_USERS["applicant_headers"]
