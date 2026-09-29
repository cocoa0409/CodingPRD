"""
Shared pytest fixtures for the Qualified Opportunity Fund compliance suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database and must build every precondition it needs
through the API itself.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    OTHER_MANAGER_HEADERS,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    """PlatformAdmin identity headers."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def manager_headers():
    """FundManager identity headers for the manager that owns the test funds."""
    return dict(MANAGER_HEADERS)


@pytest.fixture
def other_manager_headers():
    """FundManager identity headers for a manager that owns nothing."""
    return dict(OTHER_MANAGER_HEADERS)


@pytest.fixture
def measurer_headers():
    """ComplianceOfficer identity headers used for measurement calls."""
    return dict(MEASURER_HEADERS)


@pytest.fixture
def certifier_headers():
    """ComplianceOfficer identity headers used for certification calls."""
    return dict(CERTIFIER_HEADERS)
