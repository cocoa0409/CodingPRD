"""Shared pytest configuration for the PRD compliance suite."""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    actuary_headers,
    admin_headers,
    api,
    arbitrator_headers,
    other_actuary_headers,
    other_trustee_headers,
    trustee_headers,
)
