"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def steward_headers():
    return TEST_USERS["steward_headers"]


@pytest.fixture
def vendor_headers():
    # VendorOperator is entity-backed: usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def unit_manager_headers():
    # UnitManager is entity-backed: usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["unit_manager_headers"]
