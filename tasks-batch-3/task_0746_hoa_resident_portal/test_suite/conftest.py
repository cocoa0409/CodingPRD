"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
    make_anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def hoa_manager_headers():
    return TEST_USERS["hoa_manager_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def homeowner_headers():
    """Fallback headers for non-ownership scenarios (400s, 404s, opaque calls)."""
    return TEST_USERS["homeowner_headers"]


@pytest.fixture
def board_member_headers():
    """Fallback board-member headers for non-ownership scenarios."""
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def hh():
    """Return the per-instance Homeowner-role header builder."""
    return make_homeowner_headers


@pytest.fixture
def bh():
    """Return the per-instance BoardMember-role header builder."""
    return make_board_member_headers


@pytest.fixture
def ah():
    """Return the per-instance Anonymous-role header builder."""
    return make_anonymous_headers
