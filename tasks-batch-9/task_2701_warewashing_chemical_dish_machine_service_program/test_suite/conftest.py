"""
Shared pytest fixtures for the Warewashing API compliance suite.

The harness restarts the API server before every individual test, so every test
starts against an empty database and builds whatever state it needs through the
endpoints of §4 only.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import WarewashingApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ACCOUNT_MANAGER_2_HEADERS,
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_2_HEADERS,
    AUDITOR_3_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_customer_contact_headers,
    make_technician_headers,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client under test."""
    return WarewashingApiClient()


# ─── One fixture per role (§2.1) ───────────────────────────────────────


@pytest.fixture
def account_manager():
    """AccountManager headers; X-User-ID is an opaque operator identifier."""
    return ACCOUNT_MANAGER_HEADERS


@pytest.fixture
def other_account_manager():
    """A second AccountManager identity, for reported_by_user_id comparisons."""
    return ACCOUNT_MANAGER_2_HEADERS


@pytest.fixture
def platform_admin():
    """PlatformAdmin headers; drives the catalogs, telemetry, dispatch and clock."""
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture
def auditor_1():
    """First QualityAuditor identity — the drafting auditor by convention."""
    return AUDITOR_1_HEADERS


@pytest.fixture
def auditor_2():
    """Second QualityAuditor identity — the publishing auditor by convention."""
    return AUDITOR_2_HEADERS


@pytest.fixture
def auditor_3():
    """Third QualityAuditor identity — the adjudicating auditor by convention."""
    return AUDITOR_3_HEADERS


@pytest.fixture
def technician_headers():
    """
    Builder for ServiceTechnician headers. A technician's X-User-ID is the id of
    the acting Technician row, so the identity is only known after that row is
    created inside the test.
    """
    return make_technician_headers


@pytest.fixture
def customer_headers():
    """
    Builder for CustomerContact headers. A contact's X-User-ID is the id of the
    acting Customer, so the identity is only known after registration.
    """
    return make_customer_contact_headers
