"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    SECOND_DIRECTOR_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def agency_officer_headers():
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def budget_analyst_headers():
    return TEST_USERS["budget_analyst_headers"]


@pytest.fixture
def budget_director_headers():
    return TEST_USERS["budget_director_headers"]


@pytest.fixture
def legislative_fiscal_officer_headers():
    return TEST_USERS["legislative_fiscal_officer_headers"]


@pytest.fixture
def state_controller_headers():
    return TEST_USERS["state_controller_headers"]


@pytest.fixture
def second_director_headers():
    """A second BudgetDirector identity, for approvals the preparer may not perform."""
    return SECOND_DIRECTOR_HEADERS


@pytest.fixture
def anonymous_headers():
    """Headers carrying no X-User-ID and no X-User-Role."""
    return ANONYMOUS_HEADERS
