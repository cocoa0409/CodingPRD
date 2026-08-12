"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def fiduciary_manager_headers():
    return TEST_USERS["fiduciary_manager_headers"]


@pytest.fixture
def fiduciary_manager_alt_headers():
    return TEST_USERS["fiduciary_manager_alt_headers"]


@pytest.fixture
def bill_pay_specialist_headers():
    return TEST_USERS["bill_pay_specialist_headers"]


@pytest.fixture
def bill_pay_specialist_alt_headers():
    return TEST_USERS["bill_pay_specialist_alt_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def care_coordinator_headers():
    return TEST_USERS["care_coordinator_headers"]


@pytest.fixture
def care_coordinator_2_headers():
    return TEST_USERS["care_coordinator_2_headers"]


@pytest.fixture
def care_coordinator_3_headers():
    return TEST_USERS["care_coordinator_3_headers"]


@pytest.fixture
def care_coordinator_4_headers():
    return TEST_USERS["care_coordinator_4_headers"]


@pytest.fixture
def unauthenticated_headers():
    """No X-User-ID and no X-User-Role at all."""
    return NO_AUTH_HEADERS
