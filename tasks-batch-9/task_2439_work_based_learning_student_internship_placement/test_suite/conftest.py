"""Shared pytest fixtures for the Work-Based Learning API suite.

The harness restarts the server before every individual test, so each test opens
against an empty database and builds its own preconditions through the endpoints
the PRD declares.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The API client every test drives."""
    return api_client


@pytest.fixture
def coordinator_headers():
    """A `WblCoordinator`, whose `X-User-ID` is an opaque operator identifier."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_drafter_headers():
    """The coordinator who drafts agreements."""
    return TEST_USERS["coordinator_drafter_headers"]


@pytest.fixture
def coordinator_signer_headers():
    """The coordinator who executes agreements, distinct from the drafter."""
    return TEST_USERS["coordinator_signer_headers"]


@pytest.fixture
def coordinator_approver_headers():
    """The coordinator who approves training plans."""
    return TEST_USERS["coordinator_approver_headers"]


@pytest.fixture
def coordinator_awarder_headers():
    """The coordinator who awards credit, distinct from the plan approver."""
    return TEST_USERS["coordinator_awarder_headers"]


@pytest.fixture
def safety_reviewer_headers():
    """A `SafetyReviewer`, an opaque operator identity."""
    return TEST_USERS["safety_reviewer_headers"]


@pytest.fixture
def compliance_officer_headers():
    """A `ComplianceOfficer`, an opaque operator identity."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def employer_supervisor_headers():
    """An `EmployerSupervisor` not bound to any supervisor row — safe only where
    the test does not exercise an ownership check."""
    return TEST_USERS["employer_supervisor_headers"]


@pytest.fixture
def student_headers():
    """A `Student` not bound to any student row — safe only where the test does
    not exercise an ownership check."""
    return TEST_USERS["student_headers"]
