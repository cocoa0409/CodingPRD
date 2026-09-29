"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_attorney_headers,
    make_board_admin_headers,
    make_panelist_headers,
    make_provider_admin_headers,
    make_reviewer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def board_headers():
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["accreditation_reviewer_headers"]


@pytest.fixture
def panelist_headers():
    return TEST_USERS["appeals_panelist_headers"]


@pytest.fixture
def provider_admin_headers():
    """Fallback ProviderAdmin identity. Ownership-gated calls must instead use
    make_provider_admin_headers(provider["id"])."""
    return TEST_USERS["provider_admin_headers"]


@pytest.fixture
def attorney_headers():
    """Fallback Attorney identity. Ownership-gated calls must instead use
    make_attorney_headers(attorney["id"])."""
    return TEST_USERS["attorney_headers"]


@pytest.fixture
def as_provider():
    return make_provider_admin_headers


@pytest.fixture
def as_attorney():
    return make_attorney_headers


@pytest.fixture
def as_board():
    return make_board_admin_headers


@pytest.fixture
def as_reviewer():
    return make_reviewer_headers


@pytest.fixture
def as_panelist():
    return make_panelist_headers
