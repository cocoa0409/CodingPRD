"""Shared pytest fixtures for the Loyalty Liability & Breakage Accounting suite."""

import pytest

from test_helpers.api_client import api_client
from test_helpers.test_users import (
    ACCOUNTANT_2_HEADERS,
    ACCOUNTANT_HEADERS,
    CONTROLLER_2_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)


@pytest.fixture(scope="session")
def api():
    """The client every test drives the API through."""
    return api_client


@pytest.fixture
def admin_headers():
    """A ProgramAdmin, who configures the programme and never touches the ledger."""
    return PROGRAM_ADMIN_HEADERS


@pytest.fixture
def accountant_headers():
    """A LoyaltyAccountant, who prepares the ledger."""
    return ACCOUNTANT_HEADERS


@pytest.fixture
def second_accountant_headers():
    """A second LoyaltyAccountant, for preparer-versus-approver identity probes."""
    return ACCOUNTANT_2_HEADERS


@pytest.fixture
def controller_headers():
    """A Controller, who approves and closes."""
    return CONTROLLER_HEADERS


@pytest.fixture
def second_controller_headers():
    """A second Controller, so approval can come from a different human."""
    return CONTROLLER_2_HEADERS
