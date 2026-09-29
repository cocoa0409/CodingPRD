"""Shared pytest fixtures for the bank-owned life insurance funding API suite.

The server is restarted before every individual test, so each test starts
against an empty database and builds every precondition it needs through the
endpoints the requirements declare.
"""
import pytest

from test_helpers import TEST_USERS, api_client
from test_helpers.test_users import (
    make_benefits_analyst_headers,
    make_board_secretary_headers,
    make_carrier_liaison_headers,
    make_claims_administrator_headers,
    make_platform_admin_headers,
    make_risk_officer_headers,
    make_treasury_controller_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client every test drives the system through."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def benefits_analyst_headers():
    return TEST_USERS["benefits_analyst_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def treasury_controller_headers():
    return TEST_USERS["treasury_controller_headers"]


@pytest.fixture
def claims_administrator_headers():
    return TEST_USERS["claims_administrator_headers"]


@pytest.fixture
def board_secretary_headers():
    return TEST_USERS["board_secretary_headers"]


@pytest.fixture
def carrier_liaison_headers():
    """A carrier-side header set with no particular carrier ownership."""
    return TEST_USERS["carrier_liaison_headers"]


@pytest.fixture
def headers_for():
    """Build headers for an arbitrary role and operator identifier.

    Several workflows are guarded by a four-eyes rule keyed on the acting
    operator identifier rather than on the role, so tests need to vary the
    identifier while holding the role fixed.
    """
    builders = {
        "PlatformAdmin": make_platform_admin_headers,
        "BenefitsAnalyst": make_benefits_analyst_headers,
        "RiskOfficer": make_risk_officer_headers,
        "TreasuryController": make_treasury_controller_headers,
        "ClaimsAdministrator": make_claims_administrator_headers,
        "BoardSecretary": make_board_secretary_headers,
        "CarrierLiaison": make_carrier_liaison_headers,
    }

    def _build(role: str, user_id: str) -> dict:
        return builders[role](user_id)

    return _build
