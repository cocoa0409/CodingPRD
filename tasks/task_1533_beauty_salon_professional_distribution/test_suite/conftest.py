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
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def warehouse_operator_headers():
    return TEST_USERS["warehouse_operator_headers"]


@pytest.fixture
def sales_consultant_headers():
    # SalesConsultant is entity-backed: usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["sales_consultant_headers"]


@pytest.fixture
def salon_buyer_headers():
    # SalonBuyer is entity-backed: usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["salon_buyer_headers"]
