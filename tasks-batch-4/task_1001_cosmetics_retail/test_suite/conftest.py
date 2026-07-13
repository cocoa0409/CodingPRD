"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """MerchandisingAdmin — opaque identity (PRD §2.1)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def associate_headers():
    """StoreAssociate — opaque identity (PRD §2.1)."""
    return TEST_USERS["associate_headers"]


@pytest.fixture
def customer_headers():
    """Customer with a placeholder id. Only safe where no ownership check is reached;
    ownership-gated calls must use make_customer_headers(customer["id"])."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def artist_headers():
    """BeautyArtist with a placeholder id. Ownership-gated calls must use
    make_artist_headers(artist["id"])."""
    return TEST_USERS["artist_headers"]


@pytest.fixture
def no_auth_headers():
    """No X-User-ID and no X-User-Role at all (PRD §2.1)."""
    return NO_AUTH_HEADERS
