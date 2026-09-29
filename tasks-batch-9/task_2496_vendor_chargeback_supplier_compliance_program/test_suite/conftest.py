"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def second_officer_headers():
    """A second ComplianceOfficer identity, for segregation-of-duties paths."""
    return TEST_USERS["second_officer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def second_inspector_headers():
    return TEST_USERS["second_inspector_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def vendor_headers():
    """Shared Vendor constant.

    Only for calls that never resolve an owning supplier; anything
    ownership-gated must use make_vendor_headers(vendor_id).
    """
    return TEST_USERS["vendor_headers"]
