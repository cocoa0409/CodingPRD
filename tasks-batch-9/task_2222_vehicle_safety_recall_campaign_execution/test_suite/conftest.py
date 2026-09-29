"""Shared pytest fixtures for the Vehicle Safety Recall Campaigns API suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
    SAFETY_ENGINEER_2,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client under test."""
    return api_client


@pytest.fixture
def engineer():
    """Headers for the SafetyEngineer who opens the file and determines the defect."""
    return SAFETY_ENGINEER_1


@pytest.fixture
def engineer_two():
    """Headers for a second SafetyEngineer, used to release remedies."""
    return SAFETY_ENGINEER_2


@pytest.fixture
def compliance():
    """Headers for the ComplianceOfficer who files with the regulator."""
    return COMPLIANCE_OFFICER_1


@pytest.fixture
def compliance_two():
    """Headers for a second ComplianceOfficer, used to close campaigns."""
    return COMPLIANCE_OFFICER_2


@pytest.fixture
def operations():
    """Headers for the RecallOperationsManager who runs campaign operations."""
    return OPERATIONS_MANAGER


@pytest.fixture
def auditor():
    """Headers for the ClaimsAuditor who audits claims and adjudicates reimbursements."""
    return CLAIMS_AUDITOR
