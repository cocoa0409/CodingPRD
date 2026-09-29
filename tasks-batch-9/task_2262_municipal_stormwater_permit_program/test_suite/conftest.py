"""Shared pytest fixtures for the Municipal Stormwater Permit Program suite.

Every test runs against a freshly started server with an empty database, so all
fixtures are function scoped and build their preconditions through the API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_client import api_client as _api_client  # noqa: E402


@pytest.fixture
def client():
    return _api_client


@pytest.fixture
def draft_term():
    """A permit term in DRAFT with no children yet."""
    return fx.create_permit_term()


@pytest.fixture
def active_program():
    """An ACTIVE permit term with the six control measures and one outfall."""
    return fx.setup_active_program()


@pytest.fixture
def tmdl_program():
    """An ACTIVE term under a 50.00 lb/yr phosphorus allocation with OF-01."""
    return fx.setup_tmdl_program(funding_target_cents=25000)


@pytest.fixture
def approved_site(active_program):
    """A site whose plan is APPROVED and whose field is ACTIVE_DISTURBANCE."""
    return fx.setup_site_with_approved_plan(active_program["term_id"])
