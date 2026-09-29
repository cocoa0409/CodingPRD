"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers() -> dict:
    """`CapitalPlanner` identity used for estate and cycle setup."""
    return TEST_USERS["planner_headers"]


@pytest.fixture
def planner_alloc_headers() -> dict:
    """`CapitalPlanner` identity that runs allocations and is therefore barred from funding."""
    return TEST_USERS["planner_alloc_headers"]


@pytest.fixture
def planner_fund_headers() -> dict:
    """`CapitalPlanner` identity that draws capital from an allocation."""
    return TEST_USERS["planner_fund_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    """`ComplianceAuditor` identity, an opaque identifier."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def requester_headers() -> dict:
    """`ClinicalRequester` headers whose `X-User-ID` names no department row."""
    return TEST_USERS["requester_headers"]


@pytest.fixture
def director_headers() -> dict:
    """`FacilityDirector` headers whose `X-User-ID` names no facility row."""
    return TEST_USERS["director_headers"]


@pytest.fixture
def member_headers() -> dict:
    """`CommitteeMember` headers whose `X-User-ID` names no member row."""
    return TEST_USERS["member_headers"]
