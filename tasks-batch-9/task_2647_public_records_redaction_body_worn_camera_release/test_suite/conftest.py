"""Pytest configuration for the records API compliance suite.

The harness restarts the API server before every test, so each test starts from
an empty database with the logical clock at its startup default of
2026-08-01T00:00:00Z.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    baseline_scenario,
    clerk,
    supervisor,
    unit_staff,
)
