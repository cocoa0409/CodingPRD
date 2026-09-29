"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def deal_counsel_headers():
    """Headers for the DsoDealCounsel role (PRD §2.1)."""
    return TEST_USERS["deal_counsel_headers"]


@pytest.fixture
def integration_lead_headers():
    """Headers for the DsoIntegrationLead role (PRD §2.1)."""
    return TEST_USERS["integration_lead_headers"]


@pytest.fixture
def finance_controller_headers():
    """Headers for the DsoFinanceController user that reserves (PRD §2.1)."""
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def finance_settler_headers():
    """Headers for the second DsoFinanceController user that settles (PRD §3.9)."""
    return TEST_USERS["finance_settler_headers"]


@pytest.fixture
def clinical_director_headers():
    """Headers for the ClinicalDirector role; the id must resolve to a Doctor."""
    return TEST_USERS["clinical_director_headers"]


@pytest.fixture
def dentist_headers():
    """Headers for the Dentist role; the id must resolve to a Doctor."""
    return TEST_USERS["dentist_headers"]
