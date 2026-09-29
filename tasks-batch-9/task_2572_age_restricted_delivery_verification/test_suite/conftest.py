"""Shared pytest fixtures for the Age-Restricted Delivery Verification suite.

The runner starts the server under test and publishes its base URL through the
``API_BASE_URL`` environment variable before the first test executes, so the
client is constructed once per session and simply reused.

PRD 2.1 requires every request to carry `X-User-ID` and `X-User-Role`; the
per-role fixtures below hand a test the header set for each of the three opaque
operator identities. The three entity-backed roles have no session-wide header
set at all: their `X-User-ID` is the primary key of a row that only exists once
a test has created it, so tests derive those headers from the identifiers the
API minted.
"""

import pytest

from test_helpers import api_client
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
)


@pytest.fixture(scope="session")
def api():
    """The endpoint surface of PRD section 4."""
    return api_client


@pytest.fixture
def admin_headers():
    """A `PlatformAdmin` caller, whose `X-User-ID` is an opaque operator id."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def officer_headers():
    """A `ComplianceOfficer` caller whose identity the server records."""
    return dict(OFFICER_A_HEADERS)


@pytest.fixture
def second_officer_headers():
    """A second `ComplianceOfficer`, needed wherever segregation of duties bites."""
    return dict(OFFICER_B_HEADERS)


@pytest.fixture
def auditor_headers():
    """A `SecretShopperAuditor` caller, whose identity is never persisted."""
    return dict(AUDITOR_HEADERS)
