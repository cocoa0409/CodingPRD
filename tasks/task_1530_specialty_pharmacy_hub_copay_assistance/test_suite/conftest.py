"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def hub_admin_headers():
    return TEST_USERS["hub_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def financial_counselor_headers():
    return TEST_USERS["financial_counselor_headers"]


@pytest.fixture
def nurse_educator_headers():
    return TEST_USERS["nurse_educator_headers"]


@pytest.fixture
def pharmacy_partner_headers():
    return TEST_USERS["pharmacy_partner_headers"]


@pytest.fixture
def payer_reviewer_headers():
    return TEST_USERS["payer_reviewer_headers"]


@pytest.fixture
def manufacturer_monitor_headers():
    return TEST_USERS["manufacturer_monitor_headers"]
