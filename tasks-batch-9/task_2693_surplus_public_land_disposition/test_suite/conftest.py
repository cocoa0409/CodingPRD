"""Shared fixtures for the surplus public land disposition suite.

The service is relaunched before every test, so each test opens on an empty
store whose logical clock reads exactly 2026-08-01T00:00:00Z. Nothing here
mutates state: the fixtures only hand out the shared client and the role
headers, and every precondition a test needs is built inside the test from the
declared endpoints.
"""

from typing import Dict

import pytest

from test_helpers import api_client as shared_client
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_ADOPT_HEADERS,
    CLERK_AUTHORIZE_HEADERS,
    CLERK_AWARD_HEADERS,
    CLERK_DETERMINE_HEADERS,
    CLERK_HEADERS,
    COMPLIANCE_HEADERS,
    FINANCE_HEADERS,
    OFFICER_HEADERS,
)
from test_helpers.api_client import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """The HTTP client bound to the service under test."""
    return shared_client


@pytest.fixture()
def officer() -> Dict[str, str]:
    """Headers for the real property officer who runs the disposition."""
    return OFFICER_HEADERS


@pytest.fixture()
def clerk() -> Dict[str, str]:
    """Headers for a board clerk."""
    return CLERK_HEADERS


@pytest.fixture()
def clerk_adopt() -> Dict[str, str]:
    """Headers for the clerk who moves the adopting resolution."""
    return CLERK_ADOPT_HEADERS


@pytest.fixture()
def clerk_authorize() -> Dict[str, str]:
    """Headers for the clerk who moves the authorizing finding."""
    return CLERK_AUTHORIZE_HEADERS


@pytest.fixture()
def clerk_award() -> Dict[str, str]:
    """Headers for the clerk who moves the award."""
    return CLERK_AWARD_HEADERS


@pytest.fixture()
def clerk_determine() -> Dict[str, str]:
    """Headers for the clerk who rules on an appraisal challenge."""
    return CLERK_DETERMINE_HEADERS


@pytest.fixture()
def compliance() -> Dict[str, str]:
    """Headers for the compliance monitor."""
    return COMPLIANCE_HEADERS


@pytest.fixture()
def finance() -> Dict[str, str]:
    """Headers for the finance officer who keeps the funds and bidder ledgers."""
    return FINANCE_HEADERS


@pytest.fixture()
def admin() -> Dict[str, str]:
    """Headers for the system administrator who keeps the registries."""
    return ADMIN_HEADERS
