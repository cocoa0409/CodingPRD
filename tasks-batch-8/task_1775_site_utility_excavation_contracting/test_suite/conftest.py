"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the API
is already reachable at API_BASE_URL.
"""

import pytest

from test_helpers import (
    FOREMAN,
    INSPECTOR,
    OPS_ADMIN,
    PROJECT_MANAGER,
    SAFETY_OFFICER,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server process."""
    return api_client


@pytest.fixture
def ops_admin():
    return OPS_ADMIN


@pytest.fixture
def project_manager():
    return PROJECT_MANAGER


@pytest.fixture
def foreman():
    return FOREMAN


@pytest.fixture
def safety_officer():
    return SAFETY_OFFICER


@pytest.fixture
def inspector():
    return INSPECTOR


@pytest.fixture
def owner_rep_fallback():
    """Shared UtilityOwnerRep headers; only for calls that do not exercise
    ownership (the id matches no real UtilityOwner)."""
    return TEST_USERS["utility_owner_rep_headers"]
