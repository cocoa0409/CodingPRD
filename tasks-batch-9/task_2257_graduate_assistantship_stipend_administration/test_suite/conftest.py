"""Shared pytest fixtures for the stipend administration suite.

The harness restarts the service before every individual test, so every test
starts against an empty database and builds its own preconditions through the
endpoints the PRD declares.  Nothing here creates domain rows.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The endpoint client, one method per path in the PRD's endpoint table."""
    return api_client


@pytest.fixture
def grad_school_admin_headers():
    return TEST_USERS["grad_school_admin_headers"]


@pytest.fixture
def second_grad_school_admin_headers():
    return TEST_USERS["second_grad_school_admin_headers"]


@pytest.fixture
def department_admin_headers():
    return TEST_USERS["department_admin_headers"]


@pytest.fixture
def grant_accountant_headers():
    return TEST_USERS["grant_accountant_headers"]


@pytest.fixture
def faculty_supervisor_headers():
    return TEST_USERS["faculty_supervisor_headers"]


@pytest.fixture
def student_user_headers():
    """Fallback StudentUser headers for calls that are not ownership-gated.

    Ownership-gated calls must instead build headers from the acting student's
    own row id, because ``X-User-ID`` is compared to the resource's
    ``student_id``.
    """
    return TEST_USERS["student_user_headers"]
