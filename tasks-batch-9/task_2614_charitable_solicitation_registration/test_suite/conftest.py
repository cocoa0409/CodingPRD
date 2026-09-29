"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    """`ComplianceOfficer` — the charity's own filing staff."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def state_regulator_headers():
    """`StateRegulator` — the state charities bureau adjudicating filings."""
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def system_admin_headers():
    """`SystemAdmin` — seeds configuration and drives the logical clock."""
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def certifying_officer_headers():
    """`CertifyingOfficer` fallback for tests that do not exercise ownership.

    Ownership-gated calls must instead build headers from the acting
    `OfficerDisclosure` row's own `id`.
    """
    return TEST_USERS["certifying_officer_headers"]


@pytest.fixture
def fundraiser_agent_headers():
    """`FundraiserAgent` fallback for tests that do not exercise ownership.

    Ownership-gated calls must instead build headers from the acting
    `ProfessionalFundraiser` row's own `id`.
    """
    return TEST_USERS["fundraiser_agent_headers"]
