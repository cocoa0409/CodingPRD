"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, per-test restart, readiness) is owned by
prd-bench-local-runner; these fixtures only expose the API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The database is empty at the start of every test."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def parcel_owner_headers():
    """Fallback ParcelOwner headers for non-ownership tests only. Ownership-gated calls
    must use make_parcel_owner_headers(parcel_id)."""
    return TEST_USERS["parcel_owner_headers"]
