"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_member_org_delegate_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def case_manager_alt_headers():
    return TEST_USERS["case_manager_alt_headers"]


@pytest.fixture
def unmet_needs_chair_headers():
    return TEST_USERS["unmet_needs_chair_headers"]


@pytest.fixture
def member_org_delegate_headers():
    return TEST_USERS["member_org_delegate_headers"]


@pytest.fixture
def disbursement_officer_headers():
    return TEST_USERS["disbursement_officer_headers"]


@pytest.fixture
def construction_manager_headers():
    return TEST_USERS["construction_manager_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def ltrg_admin_headers():
    return TEST_USERS["ltrg_admin_headers"]


@pytest.fixture
def delegate_headers_for():
    """Factory returning delegate headers bound to one member organization id."""
    return make_member_org_delegate_headers
