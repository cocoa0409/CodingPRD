"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; every test runs against a freshly
restarted server with an empty database and the logical clock at its startup
instant (PRD §2.5).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def environmental_manager_headers():
    return TEST_USERS["environmental_manager_headers"]


@pytest.fixture
def field_sampler_headers():
    return TEST_USERS["field_sampler_headers"]


@pytest.fixture
def lab_analyst_headers():
    return TEST_USERS["lab_analyst_headers"]


@pytest.fixture
def lab_validator_headers():
    return TEST_USERS["lab_validator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def facility_inspector_headers():
    return TEST_USERS["facility_inspector_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
