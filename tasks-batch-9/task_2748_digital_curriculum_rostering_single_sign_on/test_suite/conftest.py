"""
Shared pytest fixtures for the Digital Curriculum Rostering & Single Sign-On
compliance suite.

The runner relaunches the service before every test, so each test starts against
an empty database with the logical clock at its mandatory startup default of
2026-08-01T00:00:00Z. Tests therefore build the exact world they need through the
public API and never share state with one another.
"""

import pytest

from test_helpers.api_client import RosteringApiClient
from test_helpers import test_users as users


@pytest.fixture
def api():
    """HTTP client bound to the service under test."""
    return RosteringApiClient()


@pytest.fixture
def roster_operator():
    """Headers for the district SIS data steward."""
    return users.ROSTER_OPERATOR


@pytest.fixture
def governance_officer():
    """Headers for the data-governance authority and second pair of eyes."""
    return users.DATA_GOVERNANCE_OFFICER


@pytest.fixture
def vendor_manager():
    """Headers for the vendor-facing integration owner."""
    return users.VENDOR_INTEGRATION_MANAGER


@pytest.fixture
def identity_admin():
    """Headers for the single sign-on identity administrator."""
    return users.IDENTITY_ADMIN
