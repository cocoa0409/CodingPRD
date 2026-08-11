"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def campaign_manager_headers():
    return TEST_USERS["campaign_manager_headers"]


@pytest.fixture
def list_operator_headers():
    return TEST_USERS["list_operator_headers"]


@pytest.fixture
def production_operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def account_owner_headers():
    """Shared constant. Ownership-gated calls must build headers per account."""
    return TEST_USERS["account_owner_headers"]
