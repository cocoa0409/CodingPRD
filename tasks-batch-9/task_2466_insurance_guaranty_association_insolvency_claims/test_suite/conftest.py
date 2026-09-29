"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def association_admin_headers() -> dict:
    return TEST_USERS["association_admin_headers"]


@pytest.fixture
def receiver_liaison_headers() -> dict:
    return TEST_USERS["receiver_liaison_headers"]


@pytest.fixture
def coverage_analyst_headers() -> dict:
    return TEST_USERS["coverage_analyst_headers"]


@pytest.fixture
def second_coverage_analyst_headers() -> dict:
    return TEST_USERS["second_coverage_analyst_headers"]


@pytest.fixture
def claims_committee_officer_headers() -> dict:
    return TEST_USERS["claims_committee_officer_headers"]


@pytest.fixture
def assessment_officer_headers() -> dict:
    return TEST_USERS["assessment_officer_headers"]


@pytest.fixture
def claims_adjuster_headers() -> dict:
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def defense_counsel_headers() -> dict:
    return TEST_USERS["defense_counsel_headers"]


@pytest.fixture
def member_insurer_agent_headers() -> dict:
    return TEST_USERS["member_insurer_agent_headers"]
