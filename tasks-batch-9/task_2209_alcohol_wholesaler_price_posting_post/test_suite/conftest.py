"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def filing_agent_headers():
    """Shared FilingAgent headers. Only for calls that are not ownership-gated."""
    return TEST_USERS["filing_agent_headers"]


@pytest.fixture
def certifying_officer_headers():
    """Shared CertifyingOfficer headers. Only for calls that are not ownership-gated."""
    return TEST_USERS["certifying_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    """Regulator headers. The ComplianceOfficer identifier is opaque."""
    return TEST_USERS["compliance_officer_headers"]
