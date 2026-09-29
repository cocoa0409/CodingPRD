"""Shared pytest fixtures for the School Psych Evaluation Timeline API suite.

The server is restarted before every individual test, so each test starts
against an empty database, with the logical clock reading the instant it holds
before any client moves it, and builds every precondition it needs through the
endpoints the requirements declare.
"""
import pytest

from test_helpers import TEST_USERS, api_client
from test_helpers.test_users import (
    make_compliance_officer_headers,
    make_district_admin_headers,
    make_intake_coordinator_headers,
    make_psych_services_supervisor_headers,
    make_school_psychologist_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client every test drives the system through."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["psych_services_supervisor_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def psychologist_headers():
    """A psychologist header set that resolves to no psychologist record.

    Useful only where ownership is irrelevant; anything ownership-gated must be
    called with the acting psychologist's own record id.
    """
    return TEST_USERS["school_psychologist_headers"]


@pytest.fixture
def headers_for():
    """Build headers for an arbitrary role and acting identifier.

    A `SchoolPsychologist` acts under the id of their own psychologist record,
    so tests routinely need to vary the identifier while holding the role fixed.
    """
    builders = {
        "IntakeCoordinator": make_intake_coordinator_headers,
        "SchoolPsychologist": make_school_psychologist_headers,
        "PsychServicesSupervisor": make_psych_services_supervisor_headers,
        "ComplianceOfficer": make_compliance_officer_headers,
        "DistrictAdmin": make_district_admin_headers,
    }

    def _build(role: str, user_id: str) -> dict:
        return builders[role](user_id)

    return _build
