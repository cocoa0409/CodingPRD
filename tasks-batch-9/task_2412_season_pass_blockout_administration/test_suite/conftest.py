"""Shared pytest wiring for the season pass and blockout administration suite.

Every test runs against a freshly started server with an empty database, so the
fixtures here only supply the API client and the caller identities; all domain
preconditions are built inside the tests through the declared endpoints.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    clerk_headers,
    compliance_officer_headers,
    gate_agent_headers,
    program_admin_headers,
)

# Re-exported so the scenario fixtures declared alongside the builders are
# discoverable by tests in this directory.
from test_helpers.fixtures import (  # noqa: E402,F401
    default_clock,
    design_program,
    sales_open_program,
    season_world,
    three_tier_program,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    """Headers for the season programme office."""
    return program_admin_headers()


@pytest.fixture
def clerk():
    """Headers for the pass office counter."""
    return clerk_headers()


@pytest.fixture
def gate():
    """Headers for the turnstile operator."""
    return gate_agent_headers()


@pytest.fixture
def officer():
    """Headers for the adjudicating compliance officer."""
    return compliance_officer_headers()
