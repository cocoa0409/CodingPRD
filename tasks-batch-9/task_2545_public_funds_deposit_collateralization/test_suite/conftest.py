"""Shared pytest fixtures for the Public Funds Collateral API suite.

The harness restarts the API server with an empty database before every test, so no
fixture may assume state left behind by an earlier test. Each fixture below therefore
builds what it needs from the endpoints the PRD declares.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture
def client():
    """A fresh API client bound to the server the harness just started."""
    return ApiClient()


@pytest.fixture
def regulator_headers():
    """A `StateRegulator` acting with an opaque operator identity."""
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def officer_headers():
    """A `BankCollateralOfficer` acting with an opaque operator identity."""
    return TEST_USERS["bank_collateral_officer_headers"]


@pytest.fixture
def compliance_headers():
    """A `BankComplianceOfficer` acting with an opaque operator identity."""
    return TEST_USERS["bank_compliance_officer_headers"]


@pytest.fixture
def second_compliance_headers():
    """A second `BankComplianceOfficer` identity, for segregation-of-duties scenarios."""
    return TEST_USERS["second_bank_compliance_officer_headers"]


@pytest.fixture
def second_officer_headers():
    """A second `BankCollateralOfficer` identity, for segregation-of-duties scenarios."""
    return TEST_USERS["second_bank_collateral_officer_headers"]


@pytest.fixture
def operator_headers():
    """A `SystemOperator` acting with an opaque operator identity."""
    return TEST_USERS["system_operator_headers"]
