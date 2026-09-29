"""
Shared pytest fixtures for the Supermarket Refrigerant Leak Compliance suite.

The harness restarts the API server before every individual test, so each test
starts against an empty database, with the logical clock at its start-up instant
of 2026-08-01T00:00:00Z, and builds whatever state it needs through the declared
endpoints only.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import RefrigerantComplianceApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    COMPLIANCE_MANAGER_2_HEADERS,
    COMPLIANCE_MANAGER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REGULATOR_2_HEADERS,
    REGULATOR_HEADERS,
    make_store_manager_headers,
    make_technician_headers,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client under test."""
    return RefrigerantComplianceApiClient()


# ─── One fixture per role (§2.1) ───────────────────────────────────────


@pytest.fixture
def platform_admin():
    """PlatformAdmin headers; drives the clock and the compliance sweep."""
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture
def compliance_manager():
    """ComplianceManager headers; an opaque operator identity."""
    return COMPLIANCE_MANAGER_HEADERS


@pytest.fixture
def other_compliance_manager():
    """A second ComplianceManager identity, for inspection-response comparisons."""
    return COMPLIANCE_MANAGER_2_HEADERS


@pytest.fixture
def regulator():
    """Regulator headers; by convention the principal who opens inspections."""
    return REGULATOR_HEADERS


@pytest.fixture
def other_regulator():
    """
    A second Regulator identity. Inspection closure compares the closing
    principal against `opened_by_user_id`, so a second regulator is required to
    close an inspection this one opened.
    """
    return REGULATOR_2_HEADERS


@pytest.fixture
def technician_headers():
    """
    Builder for Technician headers. A technician's `X-User-ID` is the id of their
    own Technician row, so the identity only exists once that row is created.
    """
    return make_technician_headers


@pytest.fixture
def store_manager_headers():
    """
    Builder for StoreManager headers. A store manager's `X-User-ID` is the id of
    the Store they manage, so the identity only exists once the store is created.
    """
    return make_store_manager_headers
