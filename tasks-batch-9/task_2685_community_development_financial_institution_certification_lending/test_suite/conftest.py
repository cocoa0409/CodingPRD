"""Pytest fixtures exposing the shared test infrastructure.

The client is session-scoped; the identity headers are plain dictionaries, so
each role fixture simply hands back the pre-built header set. Requests whose
outcome depends on the caller owning the subject record build their headers
per instance instead, through the builders in ``test_helpers``.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed for us."""
    return api_client


@pytest.fixture
def institution_officer_headers():
    return TEST_USERS["institution_officer_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def certification_reviewer_headers():
    return TEST_USERS["certification_reviewer_headers"]


@pytest.fixture
def certification_reviewer_two_headers():
    return TEST_USERS["certification_reviewer_two_headers"]


@pytest.fixture
def credit_underwriter_headers():
    return TEST_USERS["credit_underwriter_headers"]


@pytest.fixture
def credit_underwriter_two_headers():
    return TEST_USERS["credit_underwriter_two_headers"]


@pytest.fixture
def credit_committee_headers():
    return TEST_USERS["credit_committee_headers"]


@pytest.fixture
def credit_committee_two_headers():
    return TEST_USERS["credit_committee_two_headers"]


@pytest.fixture
def compliance_analyst_headers():
    return TEST_USERS["compliance_analyst_headers"]


@pytest.fixture
def award_administrator_headers():
    return TEST_USERS["award_administrator_headers"]


@pytest.fixture
def award_administrator_two_headers():
    return TEST_USERS["award_administrator_two_headers"]
