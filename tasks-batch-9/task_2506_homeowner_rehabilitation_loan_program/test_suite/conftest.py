"""Pytest wiring for the Homeowner Rehabilitation Loan Program suite.

Everything reusable lives in `test_helpers`; this file only exposes it to
pytest. Importing `test_helpers` also registers the error-identifier to
HTTP-status map that the response validators cross-check.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client

# Importing the composite builders' module-level fixtures makes them available
# to every test file in this directory.
from test_helpers.fixtures import (  # noqa: F401
    application,
    applicant,
    approved_write_up_case,
    awarded_case,
    bid_open_case,
    client,
    complaint_ready_case,
    contractor,
    historic_inspected_case,
    inspected_case,
    lien_recorded_case,
    ownership_verified_application,
    program_year,
    second_contractor,
    structured_loan_case,
    tabulated_case,
    verified_applicant,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared client for the `/rehab` service."""
    return api_client


@pytest.fixture
def intake_specialist_headers():
    """Headers for an `IntakeSpecialist`."""
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def rehab_specialist_headers():
    """Headers for a `RehabSpecialist`."""
    return TEST_USERS["rehab_specialist_headers"]


@pytest.fixture
def second_rehab_specialist_headers():
    """Headers for a second, distinct `RehabSpecialist`."""
    return TEST_USERS["second_rehab_specialist_headers"]


@pytest.fixture
def inspector_headers():
    """Headers for an `Inspector`."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def second_inspector_headers():
    """Headers for a second, distinct `Inspector`."""
    return TEST_USERS["second_inspector_headers"]


@pytest.fixture
def loan_officer_headers():
    """Headers for a `LoanOfficer`."""
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def program_manager_headers():
    """Headers for a `ProgramManager`."""
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def applicant_headers():
    """Headers for an `Applicant` that owns no rows, for role-only probes."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def contractor_headers():
    """Headers for a `Contractor` that owns no rows, for role-only probes."""
    return TEST_USERS["contractor_headers"]
