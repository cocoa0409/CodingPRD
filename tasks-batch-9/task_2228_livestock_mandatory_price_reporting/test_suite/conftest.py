"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["ProgramAdmin"]


@pytest.fixture
def market_analyst_headers():
    return TEST_USERS["MarketAnalyst"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["ComplianceAuditor"]


@pytest.fixture
def penalty_officer_headers():
    return TEST_USERS["PenaltyOfficer"]


@pytest.fixture
def public_user_headers():
    return TEST_USERS["PublicUser"]
