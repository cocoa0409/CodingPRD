"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, per-test restart, PYTHONPATH) is owned by
prd-bench-local-runner. These fixtures only wire test_helpers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def employer_agent_headers():
    return TEST_USERS["employer_agent_headers"]


@pytest.fixture
def dol_headers():
    return TEST_USERS["dol_analyst_headers"]


@pytest.fixture
def uscis_headers():
    return TEST_USERS["uscis_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]
