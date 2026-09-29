"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def marketplace_ops_headers():
    return TEST_USERS["marketplace_ops_headers"]


@pytest.fixture
def marketplace_ops_reviewer_headers():
    return TEST_USERS["marketplace_ops_reviewer_headers"]


@pytest.fixture
def marketplace_ops_second_reviewer_headers():
    return TEST_USERS["marketplace_ops_second_reviewer_headers"]


@pytest.fixture
def marketplace_ops_claims_headers():
    return TEST_USERS["marketplace_ops_claims_headers"]


@pytest.fixture
def marketplace_ops_dock_headers():
    return TEST_USERS["marketplace_ops_dock_headers"]


@pytest.fixture
def marketplace_ops_closer_headers():
    return TEST_USERS["marketplace_ops_closer_headers"]


@pytest.fixture
def marketplace_ops_sweeper_headers():
    return TEST_USERS["marketplace_ops_sweeper_headers"]


@pytest.fixture
def trust_safety_headers():
    return TEST_USERS["trust_safety_headers"]


@pytest.fixture
def trust_safety_reverser_headers():
    return TEST_USERS["trust_safety_reverser_headers"]


@pytest.fixture
def seller_ops_headers():
    return TEST_USERS["seller_ops_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]
