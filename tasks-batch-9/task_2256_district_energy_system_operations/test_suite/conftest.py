"""Shared pytest fixtures for the District Energy System Operations suite.

The harness restarts the server before every individual test, so each test runs
against an empty database and builds whatever preconditions it needs through the
published endpoints. These fixtures therefore hand out only the client and the
role header sets — never shared data.
"""

import pytest

from test_helpers import (
    BILLING_ANALYST,
    BILLING_ANALYST_ALT,
    DISPATCH_OPERATOR,
    DISPATCH_OPERATOR_ALT,
    FIELD_TECHNICIAN,
    FIELD_TECHNICIAN_ALT,
    NETWORK_ENGINEER,
    NETWORK_ENGINEER_ALT,
    SYSTEM_CONTROLLER,
    SYSTEM_CONTROLLER_ALT,
    api_client,
    make_customer_account_headers,
)


@pytest.fixture(scope="session")
def api():
    """The typed client for every District Energy endpoint."""
    return api_client


@pytest.fixture
def controller():
    """Headers for the system controller who owns the clock and the fleet."""
    return SYSTEM_CONTROLLER


@pytest.fixture
def controller_alt():
    """A second system controller, for reviews the author may not perform."""
    return SYSTEM_CONTROLLER_ALT


@pytest.fixture
def operator():
    """Headers for the dispatch operator who authors forecasts and plans."""
    return DISPATCH_OPERATOR


@pytest.fixture
def operator_alt():
    """A second dispatch operator."""
    return DISPATCH_OPERATOR_ALT


@pytest.fixture
def engineer():
    """Headers for the network engineer who owns segments, permits and projects."""
    return NETWORK_ENGINEER


@pytest.fixture
def engineer_alt():
    """A second network engineer."""
    return NETWORK_ENGINEER_ALT


@pytest.fixture
def technician():
    """Headers for the field technician who installs meters and reports work."""
    return FIELD_TECHNICIAN


@pytest.fixture
def technician_alt():
    """A second field technician, so a job can be closed by someone else."""
    return FIELD_TECHNICIAN_ALT


@pytest.fixture
def analyst():
    """Headers for the billing analyst who owns tariffs, customers and invoices."""
    return BILLING_ANALYST


@pytest.fixture
def analyst_alt():
    """A second billing analyst."""
    return BILLING_ANALYST_ALT


@pytest.fixture
def customer():
    """A builder for connected-customer headers keyed on an agreement id."""
    return make_customer_account_headers
