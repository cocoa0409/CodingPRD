"""Pytest fixtures exposing the `test_helpers` infrastructure.

The runner owns the API server lifecycle and the `PYTHONPATH`, so this file is a
thin bridge: a session-scoped client plus one header fixture per role named in
PRD §2.1.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def design_engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def design_engineer_alt_headers():
    return TEST_USERS["design_engineer_alt_headers"]


@pytest.fixture
def test_lab_technician_headers():
    return TEST_USERS["test_lab_technician_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def sales_engineer_headers():
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def sales_engineer_alt_headers():
    return TEST_USERS["sales_engineer_alt_headers"]


@pytest.fixture
def plant_supervisor_headers():
    return TEST_USERS["plant_supervisor_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def install_contractor_headers():
    return TEST_USERS["install_contractor_headers"]


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]
