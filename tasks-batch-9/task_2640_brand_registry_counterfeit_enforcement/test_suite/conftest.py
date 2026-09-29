"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, UNAUTHENTICATED_HEADERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the harness."""
    return api_client


@pytest.fixture
def brand_administrator_headers():
    return TEST_USERS["brand_administrator_headers"]


@pytest.fixture
def enforcement_analyst_headers():
    return TEST_USERS["enforcement_analyst_headers"]


@pytest.fixture
def authorized_representative_headers():
    """Placeholder representative identity naming no designation row.

    Ownership-gated calls must instead build headers from a real designation id
    with ``make_authorized_representative_headers``.
    """
    return TEST_USERS["authorized_representative_headers"]


@pytest.fixture
def marketplace_liaison_headers():
    return TEST_USERS["marketplace_liaison_headers"]


@pytest.fixture
def customs_coordinator_headers():
    return TEST_USERS["customs_coordinator_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def unauthenticated_headers():
    return UNAUTHENTICATED_HEADERS
