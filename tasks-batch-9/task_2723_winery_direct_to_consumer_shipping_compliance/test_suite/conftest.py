"""pytest configuration for the Winery DTC Shipping Compliance test suite.

The harness restarts the server and empties the database before every individual
test, so every fixture below rebuilds its preconditions from scratch.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_helpers.api_errors  # noqa: E402,F401  (registers PRD §5 status map)
from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    bare_landscape,
    cleared_order,
    clock,
    club_landscape,
    delivered_order,
    in_transit_order,
    labeled_order,
    landscape,
    landscape_pending_permit,
    landscape_unverified_consumer,
    override_pending_order,
    returned_order,
    suspended_permit_order,
)
