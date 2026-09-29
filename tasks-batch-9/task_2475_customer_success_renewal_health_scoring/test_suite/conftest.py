"""Pytest wiring for the customer-success test suite.

The harness restarts the API server before every individual test, so there are
no session-scoped fixtures here: every fixture below is function-scoped and
opens against an empty database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401  -- fixture registration
    active_enrollment,
    active_play_account,
    api,
    clock,
    committed_case,
    delivered_case,
    digital_smb_account,
    escalated_account,
    green_account,
    handed_off_opportunity,
    open_account,
    open_green_account,
    roster_and_account,
    submitted_forecast,
    trending_account,
    two_managers_one_account,
)
