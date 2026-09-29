"""Shared fixtures for the staffing reporting compliance suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.fixtures import *  # noqa: E402,F401,F403
from test_helpers.test_users import (  # noqa: E402
    TEST_USERS,
    make_appeals_reviewer_headers,
    make_cms_publisher_headers,
    make_platform_admin_headers,
    make_state_auditor_headers,
)
from test_helpers.constants import (  # noqa: E402
    ACCEPTING_AUDITOR_USER_ID,
    CASE_AUDITOR_USER_ID,
    READING_AUDITOR_USER_ID,
    VERIFYING_AUDITOR_USER_ID,
)


@pytest.fixture
def api():
    """The live API client, pointed at the server under test."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return make_platform_admin_headers()


@pytest.fixture
def verifying_auditor_headers():
    return make_state_auditor_headers(VERIFYING_AUDITOR_USER_ID)


@pytest.fixture
def accepting_auditor_headers():
    return make_state_auditor_headers(ACCEPTING_AUDITOR_USER_ID)


@pytest.fixture
def reading_auditor_headers():
    return make_state_auditor_headers(READING_AUDITOR_USER_ID)


@pytest.fixture
def case_auditor_headers():
    return make_state_auditor_headers(CASE_AUDITOR_USER_ID)


@pytest.fixture
def cms_publisher_headers():
    return make_cms_publisher_headers()


@pytest.fixture
def appeals_reviewer_headers():
    return make_appeals_reviewer_headers()


@pytest.fixture
def unresolvable_coordinator_headers():
    """A `StaffingCoordinator` identity that resolves to no `Worker` row."""
    return TEST_USERS["staffing_coordinator_headers"]


@pytest.fixture
def unresolvable_administrator_headers():
    """A `FacilityAdministrator` identity that resolves to no `Worker` row."""
    return TEST_USERS["facility_administrator_headers"]


@pytest.fixture
def unresolvable_vendor_headers():
    """A `VendorRepresentative` identity that resolves to no vendor row."""
    return TEST_USERS["vendor_representative_headers"]
