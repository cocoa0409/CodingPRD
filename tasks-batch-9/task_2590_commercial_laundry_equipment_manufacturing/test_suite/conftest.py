"""Shared pytest configuration for the commercial-laundry test suite.

The harness restarts the API server and empties its database before every single
test, so every fixture here is function-scoped and rebuilds its own preconditions
from scratch through the PRD's endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)

# Re-export every composite fixture so test modules can request them by name.
from test_helpers.fixtures import (  # noqa: E402,F401
    accepted_unit,
    authorized_distributor,
    certified_model,
    floor_environment,
    model,
    pending_distributor,
    released_model,
    submitted_claim,
    three_stations,
    unit_in_qa_hold,
    warranty_environment,
)


@pytest.fixture
def api():
    """A client bound to the API under test."""
    return ApiClient()
