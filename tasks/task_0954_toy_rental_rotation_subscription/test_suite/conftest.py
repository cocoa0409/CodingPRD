"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN,
    ANONYMOUS,
    MEMBER_UNOWNED,
    OPS,
    SUPPORT,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS


@pytest.fixture
def ops_headers():
    return OPS


@pytest.fixture
def support_headers():
    return SUPPORT


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def unowned_member_headers():
    """A Member-role identity that owns nothing — for 401/403/404 probes only."""
    return MEMBER_UNOWNED
