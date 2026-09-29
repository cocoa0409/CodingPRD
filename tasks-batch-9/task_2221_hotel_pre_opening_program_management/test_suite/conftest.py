"""Shared pytest configuration for the pre-opening compliance suite.

The runner restarts the server before every individual test, so every fixture
here builds its preconditions from an empty database through the public API.
Importing ``test_helpers`` also registers the error catalogue with the shared
validators, which is why ``validate_error`` can cross-check HTTP status codes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401  (re-exported as fixtures)
    api,
    baselined,
    booking_open,
    budgeted_program,
    clock_at_default,
    construction_complete,
    licensing,
    planning_program_with_network,
    program,
    soft_opening_ready,
)
