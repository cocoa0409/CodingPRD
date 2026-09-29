"""Pytest fixtures exposing the shared test infrastructure.

The runner restarts the API server before every test, so each test begins
against an empty database and builds its own preconditions through the
endpoints the PRD declares.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the API under test."""
    return api_client


@pytest.fixture
def compliance_officer_headers() -> dict:
    """ComplianceOfficer identity (opaque operator id, PRD §2.1)."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers() -> dict:
    """A second, distinct ComplianceOfficer operator (PRD §2.9)."""
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def nurse_case_manager_headers() -> dict:
    """NurseCaseManager identity not bound to any clinician record."""
    return TEST_USERS["nurse_case_manager_headers"]


@pytest.fixture
def rehab_physician_headers() -> dict:
    """RehabPhysician identity not bound to any clinician record."""
    return TEST_USERS["rehab_physician_headers"]


@pytest.fixture
def therapy_lead_headers() -> dict:
    """TherapyLead identity not bound to any clinician record."""
    return TEST_USERS["therapy_lead_headers"]


@pytest.fixture
def him_coder_headers() -> dict:
    """HimCoder identity not bound to any clinician record."""
    return TEST_USERS["him_coder_headers"]
