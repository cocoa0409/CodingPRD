"""Fixtures shared by the Pentest Assurance API test suite.

The harness relaunches the API and resets its store before every individual test,
so a test never needs to clean up after itself and may assume an empty programme.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import PentestApiClient, register_error_statuses  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    admin_headers,
    compliance_officer_headers,
    program_manager_headers,
    remediation_owner_headers,
)
from test_helpers.test_users import (  # noqa: E402
    CO_ALT_USER_ID,
    OWNER_ALT_USER_ID,
    PM_ALT_USER_ID,
)

register_error_statuses()


@pytest.fixture
def client():
    """A client for the freshly launched API."""
    return PentestApiClient()


@pytest.fixture
def admin():
    """Headers for the platform administrator who curates the asset inventory."""
    return admin_headers()


@pytest.fixture
def program_manager():
    """Headers for the programme manager who plans and runs engagements."""
    return program_manager_headers()


@pytest.fixture
def other_program_manager():
    """Headers for a second programme manager, used for ownership boundaries."""
    return program_manager_headers(PM_ALT_USER_ID)


@pytest.fixture
def compliance_officer():
    """Headers for the compliance officer who signs and clears work."""
    return compliance_officer_headers()


@pytest.fixture
def other_compliance_officer():
    """Headers for a second compliance officer, used for independence rules."""
    return compliance_officer_headers(CO_ALT_USER_ID)


@pytest.fixture
def remediation_owner():
    """Headers for the engineer who owns a remediation."""
    return remediation_owner_headers()


@pytest.fixture
def other_remediation_owner():
    """Headers for an engineer who owns nothing, used for ownership boundaries."""
    return remediation_owner_headers(OWNER_ALT_USER_ID)
