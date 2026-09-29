"""Pytest bridge: exposes the shared API client and the role headers.

The runner starts a fresh server before every individual test, so every test
builds all of its own preconditions from scratch through the endpoints the PRD
declares in §4.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The API client bound to the running service."""
    return api_client


@pytest.fixture
def host_operations_headers():
    """PRD §2.1: HostOperations is the agency's operations desk."""
    return TEST_USERS["host_operations_headers"]


@pytest.fixture
def host_controller_headers():
    """PRD §2.1: HostController is the agency's controller."""
    return TEST_USERS["host_controller_headers"]


@pytest.fixture
def host_controller_2_headers():
    """A second HostController identity, because PRD §2.11 forbids the X-User-ID
    that calculated a run from posting it."""
    return TEST_USERS["host_controller_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    """PRD §2.1: ComplianceOfficer decides every credential."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def advisor_headers():
    """PRD §2.1: Advisor is an independent travel advisor acting for itself."""
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def supplier_portal_headers():
    """PRD §2.1: SupplierPortal is a travel supplier acting through the agency's
    supplier portal."""
    return TEST_USERS["supplier_portal_headers"]
