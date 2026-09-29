"""Shared pytest fixtures for the Public Charging Uptime Compliance API suite.

Every test runs against a freshly launched server with an empty database, so
each fixture builds the state it needs from scratch through declared endpoints.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The HTTP client wrapper covering every endpoint in the PRD."""
    return api_client


@pytest.fixture
def network_operator_headers():
    return TEST_USERS["network_operator_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def customer_support_agent_headers():
    return TEST_USERS["customer_support_agent_headers"]


@pytest.fixture
def host_site_manager_headers():
    """Fallback only.  Ownership-gated calls must build headers from the real
    host site id, because for this role `X-User-ID` is the id of the acting
    host site."""
    return TEST_USERS["host_site_manager_headers"]
