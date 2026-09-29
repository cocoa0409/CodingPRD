"""Shared pytest configuration for the Club Demo Sampling Program suite.

The server under test is restarted with an empty database before each test, so
every fixture here is function-scoped and builds the state it needs from
scratch through documented endpoints only.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402,F401
    ADMIN_BILLING_HEADERS,
    ADMIN_CONTROLLER_HEADERS,
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
)

# Fixtures live in test_helpers.fixtures; importing them here registers them
# for every test module in the suite.
from test_helpers.fixtures import (  # noqa: E402,F401
    capacity_boundary_setup,
    capacity_precedence_setup,
    cert_precedence_setup,
    credit_bracket_state,
    credit_cascade_state,
    equipment_buffer_setup,
    lift_event_ready,
    pool_revocation_setup,
    reliability_seed,
    restricted_club_events,
    rounding_event_ready,
    rounding_invoice,
    third_strike_state,
    touching_shift_setup,
    two_dimension_event,
    variance_blocked_invoice,
    void_receivable_invoice,
    void_redraft_invoice,
    zero_delivery_event,
)


@pytest.fixture
def api():
    """HTTP client bound to the running service."""
    return ApiClient()


@pytest.fixture
def program_admin_headers():
    """A ProgramAdmin operator identity."""
    return ADMIN_HQ_HEADERS


@pytest.fixture
def billing_admin_headers():
    """A second, distinct ProgramAdmin operator used for invoice issuance."""
    return ADMIN_BILLING_HEADERS


@pytest.fixture
def controller_admin_headers():
    """A third ProgramAdmin operator used for credit decisions."""
    return ADMIN_CONTROLLER_HEADERS


@pytest.fixture
def staffing_coordinator_headers():
    """A StaffingCoordinator operator identity."""
    return STAFF_OPS_HEADERS
