"""Shared pytest fixtures for the State Veterans Home API suite.

The server is restarted before each test, so every test begins against an empty
database with the logical clock at its starting instant. Scenario setup is
therefore performed inside each test through the builders in `test_helpers`.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import register_error_status_map
from test_helpers.test_users import (
    make_admissions_coordinator_headers,
    make_business_office_manager_headers,
    make_clinical_assessor_headers,
    make_federal_per_diem_auditor_headers,
    make_state_program_admin_headers,
    make_survey_agency_headers,
)


@pytest.fixture(scope="session", autouse=True)
def error_status_map():
    """Pair every error identifier with the HTTP status the PRD assigns it."""
    register_error_status_map()


@pytest.fixture
def api():
    return ApiClient()


@pytest.fixture
def admin_headers():
    return make_state_program_admin_headers()


@pytest.fixture
def coordinator_headers():
    return make_admissions_coordinator_headers()


@pytest.fixture
def assessor_headers():
    return make_clinical_assessor_headers()


@pytest.fixture
def bom_headers():
    return make_business_office_manager_headers()


@pytest.fixture
def auditor_headers():
    return make_federal_per_diem_auditor_headers()


@pytest.fixture
def surveyor_headers():
    return make_survey_agency_headers()
