"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    api_client,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# One fixture per PRD role. Entity-backed role fixtures return the SHARED-constant
# form for tests that don't need ownership; ownership-gated fixtures build headers
# with `make_*_headers(entity_id)` inline.
@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def provider_staff_headers():
    return TEST_USERS["provider_staff_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def funder_reporter_headers():
    return TEST_USERS["funder_reporter_headers"]
