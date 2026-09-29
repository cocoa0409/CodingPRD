"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def finance_director_headers():
    return TEST_USERS["finance_director_headers"]


@pytest.fixture
def disclosure_officer_headers():
    """The preparing officer: attests content items, so it may not assemble."""
    return TEST_USERS["disclosure_officer_headers"]


@pytest.fixture
def assembler_officer_headers():
    """A second, distinct DisclosureOfficer used for assembly."""
    return TEST_USERS["assembler_officer_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def second_reviewer_headers():
    """A second, distinct ComplianceReviewer used for posting official statements."""
    return TEST_USERS["second_reviewer_headers"]


@pytest.fixture
def dissemination_agent_headers():
    """A DisseminationAgent whose X-User-ID resolves to no engagement row.

    Any test that needs a *working* agent must build headers per engagement with
    `make_agent_headers(engagement_id)`, since the engagement's own id is the
    agent's identity.
    """
    return TEST_USERS["dissemination_agent_headers"]
