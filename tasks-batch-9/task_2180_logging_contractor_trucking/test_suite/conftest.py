"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin — seeds reference data and drives the logical clock."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def ops_headers():
    """OperationsManager — the logging contractor's woods boss."""
    return TEST_USERS["ops_headers"]


@pytest.fixture
def safety_headers():
    """SafetyOfficer — the independent compliance auditor."""
    return TEST_USERS["safety_headers"]


@pytest.fixture
def accountant_headers():
    """SettlementAccountant acting as the compiler acct-1."""
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def approver_headers():
    """A second SettlementAccountant, acct-2, for segregation of duties."""
    return TEST_USERS["accountant_two_headers"]


@pytest.fixture
def carrier_headers():
    """HaulContractor headers not bound to any real carrier id."""
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def scaler_headers():
    """MillScaler headers not bound to any real mill id."""
    return TEST_USERS["scaler_headers"]
