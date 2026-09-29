"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def second_engineer_headers():
    return TEST_USERS["second_design_engineer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["design_approver_headers"]


@pytest.fixture
def second_approver_headers():
    return TEST_USERS["second_design_approver_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["test_lab_technician_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["production_supervisor_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def certification_body_headers():
    return TEST_USERS["certification_body_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["safety_director_headers"]


@pytest.fixture
def sysop_headers():
    return TEST_USERS["system_operator_headers"]
