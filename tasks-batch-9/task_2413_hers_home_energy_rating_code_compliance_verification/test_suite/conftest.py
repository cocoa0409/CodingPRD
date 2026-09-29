"""Pytest configuration for the HERS Rating & Code Compliance API suite.

The runner starts the server, relaunches it with an empty database before every
individual test and injects `API_BASE_URL`; tests therefore assume a running,
empty API and build every precondition through the PRD's own endpoints.
"""

import os
import sys

# Make the sibling `test_helpers` package importable regardless of how pytest
# was invoked.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    admin,
    api,
    confirmed_failing_world,
    confirmed_passing_world,
    rating_world,
    registered_world,
    sample_world,
    selected_sample_world,
)
