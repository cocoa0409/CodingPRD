"""Shared fixtures for the Motor Fuel Tax API suite.

The API restarts against an empty database before every test, so each test
builds the state it needs through the endpoints the PRD declares.
"""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_audit_manager_headers,
    make_field_inspector_headers,
    make_licensee_agent_headers,
    make_licensing_officer_headers,
    make_returns_examiner_headers,
    make_tax_supervisor_headers,
)
from test_helpers.fixtures import world  # noqa: F401  (re-exported as a fixture)
from test_helpers.test_users import (
    AUDIT_MANAGER_ALT_ID,
    AUDIT_MANAGER_ID,
    RETURNS_EXAMINER_ALT_ID,
    RETURNS_EXAMINER_ID,
    TAX_SUPERVISOR_ALT_ID,
    TAX_SUPERVISOR_ID,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The typed client for the API under test."""
    return api_client


@pytest.fixture
def officer_headers():
    """A `LicensingOfficer` acting identity."""
    return make_licensing_officer_headers()


@pytest.fixture
def examiner_headers():
    """A `ReturnsExaminer` acting identity."""
    return make_returns_examiner_headers(RETURNS_EXAMINER_ID)


@pytest.fixture
def examiner_alt_headers():
    """A second, distinct `ReturnsExaminer` acting identity."""
    return make_returns_examiner_headers(RETURNS_EXAMINER_ALT_ID)


@pytest.fixture
def supervisor_headers():
    """A `TaxSupervisor` acting identity."""
    return make_tax_supervisor_headers(TAX_SUPERVISOR_ID)


@pytest.fixture
def supervisor_alt_headers():
    """A second, distinct `TaxSupervisor` acting identity."""
    return make_tax_supervisor_headers(TAX_SUPERVISOR_ALT_ID)


@pytest.fixture
def manager_headers():
    """An `AuditManager` acting identity."""
    return make_audit_manager_headers(AUDIT_MANAGER_ID)


@pytest.fixture
def manager_alt_headers():
    """A second, distinct `AuditManager` acting identity."""
    return make_audit_manager_headers(AUDIT_MANAGER_ALT_ID)


@pytest.fixture
def inspector_headers():
    """A `FieldInspector` acting identity."""
    return make_field_inspector_headers()


@pytest.fixture
def agent_headers():
    """Build `LicenseeAgent` headers for a given licensee id."""
    return make_licensee_agent_headers
