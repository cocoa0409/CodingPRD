"""Shared pytest fixtures for the Federated Fundraising Campaign Allocation API.

The harness restarts the service before every individual test, so each test
begins against an empty data store and builds all the state it needs through
the API itself. Nothing is shared across tests.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers error statuses)
from test_helpers.api_client import api_client as _api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_admin_headers,
    make_allocations_director_headers,
    make_finance_reviewer_headers,
)


@pytest.fixture
def api():
    """The API client, one instance per test."""
    return _api_client


@pytest.fixture
def admin_headers():
    """Headers for `UnitedFundAdmin`, whose identity is opaque (PRD 2.1)."""
    return make_admin_headers()


@pytest.fixture
def finance_headers():
    """Headers for `FinanceReviewer`, whose identity is opaque (PRD 2.1)."""
    return make_finance_reviewer_headers()


@pytest.fixture
def director_headers():
    """Headers for `AllocationsDirector`, whose identity is opaque (PRD 2.1)."""
    return make_allocations_director_headers()
