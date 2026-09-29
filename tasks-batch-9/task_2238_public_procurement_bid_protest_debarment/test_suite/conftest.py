"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, api_client
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    DEBARMENT_AUTHORITY_2_HEADERS,
    DEBARMENT_AUTHORITY_HEADERS,
    HEARING_OFFICER_2_HEADERS,
    HEARING_OFFICER_HEADERS,
    OFFICER_2_HEADERS,
    OFFICER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """SystemAdmin, the only role that may register vendors or move the clock."""
    return ADMIN_HEADERS


@pytest.fixture
def officer_headers():
    """ProcurementOfficer U-OFFICER-1."""
    return OFFICER_HEADERS


@pytest.fixture
def second_officer_headers():
    """ProcurementOfficer U-OFFICER-2."""
    return OFFICER_2_HEADERS


@pytest.fixture
def reviewer_headers():
    """ResponsibilityReviewer U-REVIEWER-1."""
    return REVIEWER_HEADERS


@pytest.fixture
def second_reviewer_headers():
    """ResponsibilityReviewer U-REVIEWER-2."""
    return REVIEWER_2_HEADERS


@pytest.fixture
def hearing_officer_headers():
    """HearingOfficer U-HEARING-1."""
    return HEARING_OFFICER_HEADERS


@pytest.fixture
def second_hearing_officer_headers():
    """HearingOfficer U-HEARING-2."""
    return HEARING_OFFICER_2_HEADERS


@pytest.fixture
def debarment_authority_headers():
    """DebarmentAuthority U-DEBAR-1."""
    return DEBARMENT_AUTHORITY_HEADERS


@pytest.fixture
def second_debarment_authority_headers():
    """DebarmentAuthority U-DEBAR-2."""
    return DEBARMENT_AUTHORITY_2_HEADERS


@pytest.fixture
def helpers():
    """The state-building fixture module."""
    return fx
