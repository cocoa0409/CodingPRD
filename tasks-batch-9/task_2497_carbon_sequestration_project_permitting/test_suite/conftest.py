"""Pytest fixtures exposing the test_helpers infrastructure.

Every test builds its own world from scratch: the harness relaunches the service
and empties the store before each individual test, so nothing survives between
tests and every precondition is created through the documented endpoints.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def program_admin_headers():
    """ProgramAdmin — opens projects and drives the logical clock."""
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def project_developer_headers():
    """ProjectDeveloper — the operator side of every application."""
    return TEST_USERS["project_developer_headers"]


@pytest.fixture
def regulatory_reviewer_headers():
    """RegulatoryReviewer — rules on models, plans, permits and orders."""
    return TEST_USERS["regulatory_reviewer_headers"]


@pytest.fixture
def second_reviewer_headers():
    """A second RegulatoryReviewer identity, for segregation-of-duties paths."""
    return TEST_USERS["second_reviewer_headers"]


@pytest.fixture
def other_reviewer_headers():
    """A third RegulatoryReviewer identity, unrelated to any prior review."""
    return TEST_USERS["other_reviewer_headers"]


@pytest.fixture
def independent_verifier_headers():
    """IndependentVerifier — the only role that may verify a tax credit claim."""
    return TEST_USERS["independent_verifier_headers"]


@pytest.fixture
def landowner_headers():
    """Shared Landowner constant.

    Only for calls that never resolve an owning tract; anything gated on the
    tract's landowner_user_id must use make_landowner_headers(user_id).
    """
    return TEST_USERS["landowner_headers"]


@pytest.fixture
def second_landowner_headers():
    return TEST_USERS["second_landowner_headers"]


@pytest.fixture
def third_landowner_headers():
    return TEST_USERS["third_landowner_headers"]


@pytest.fixture
def stranger_landowner_headers():
    """A Landowner who owns none of the tracts under test."""
    return TEST_USERS["stranger_landowner_headers"]
