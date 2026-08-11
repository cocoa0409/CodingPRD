"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def vendor_admin_headers():
    return TEST_USERS["vendor_admin_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def second_technician_headers():
    return TEST_USERS["second_technician_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def second_supervisor_headers():
    return TEST_USERS["second_supervisor_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def second_adjudicator_headers():
    return TEST_USERS["second_adjudicator_headers"]


@pytest.fixture
def destination_headers():
    return TEST_USERS["destination_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
