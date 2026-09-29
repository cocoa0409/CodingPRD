"""
Shared pytest fixtures for the suite.

The fixtures themselves live beside the rest of the test infrastructure; this
module only re-exports them so that pytest collects them for every test file.
The server is restarted before each test, so every fixture builds its
preconditions from an empty database using declared endpoints only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    active_program,
    admin_headers,
    api,
    assigned_battlecard,
    completed_interview,
    draft_battlecard,
    draft_program,
    enablement_headers,
    legal_headers,
    product_gap,
    product_headers,
    published_battlecard,
    ratified_attribution,
    registry,
    rep_headers,
    scheduled_interview,
    selected_deal,
    world,
)
