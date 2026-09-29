"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2"]


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin"]


@pytest.fixture
def preparer_headers():
    return TEST_USERS["preparer"]


@pytest.fixture
def preparer_2_headers():
    return TEST_USERS["preparer_2"]


@pytest.fixture
def filing_agent_headers():
    return TEST_USERS["filing_agent"]


@pytest.fixture
def filing_agent_2_headers():
    return TEST_USERS["filing_agent_2"]
