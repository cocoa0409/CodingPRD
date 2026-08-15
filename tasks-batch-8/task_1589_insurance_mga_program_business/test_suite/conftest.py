"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def mga_underwriter_headers():
    return TEST_USERS["mga_underwriter_headers"]


@pytest.fixture
def mga_finance_headers():
    return TEST_USERS["mga_finance_headers"]


@pytest.fixture
def carrier_auditor_headers():
    return TEST_USERS["carrier_auditor_headers"]


@pytest.fixture
def carrier_underwriter_headers():
    return TEST_USERS["carrier_underwriter_headers"]


@pytest.fixture
def tpa_adjuster_headers():
    return TEST_USERS["tpa_adjuster_headers"]
