"""Shared pytest wiring for the job classification exemption audit suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.fixtures import (  # noqa: E402,F401
    ca_engagement,
    ca_planning_engagement,
    corroborated_engagement,
    determined_engagement,
    pinned_clock,
    submitted_analysis,
    willful_ca_engagement,
)
from test_helpers.test_users import (  # noqa: E402
    AUDITOR_HEADERS,
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPENSATION_MANAGER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    EMPLOYEE_RELATIONS_LEAD_HEADERS,
    LEGAL_COUNSEL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client pointed at the service under test."""
    return api_client


@pytest.fixture
def program_admin() -> dict:
    return PROGRAM_ADMIN_HEADERS


@pytest.fixture
def compliance_analyst() -> dict:
    return COMPLIANCE_ANALYST_HEADERS


@pytest.fixture
def classification_reviewer() -> dict:
    return CLASSIFICATION_REVIEWER_HEADERS


@pytest.fixture
def compensation_manager() -> dict:
    return COMPENSATION_MANAGER_HEADERS


@pytest.fixture
def employee_relations_lead() -> dict:
    return EMPLOYEE_RELATIONS_LEAD_HEADERS


@pytest.fixture
def legal_counsel() -> dict:
    return LEGAL_COUNSEL_HEADERS


@pytest.fixture
def auditor() -> dict:
    return AUDITOR_HEADERS
