"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def event_coordinator_headers():
    return TEST_USERS["event_coordinator_headers"]


@pytest.fixture
def containment_inspector_headers():
    return TEST_USERS["containment_inspector_headers"]


@pytest.fixture
def site_approver_headers():
    return TEST_USERS["site_approver_headers"]


@pytest.fixture
def eligibility_clerk_headers():
    return TEST_USERS["eligibility_clerk_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def unload_tech_headers():
    return TEST_USERS["unload_tech_headers"]


@pytest.fixture
def packing_contractor_headers():
    return TEST_USERS["packing_contractor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
