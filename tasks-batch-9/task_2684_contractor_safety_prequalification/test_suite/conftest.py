"""Pytest configuration for the contractor safety prequalification suite.

The shared fixtures live in the sibling ``test_helpers`` package at the task
root, so that directory is placed on ``sys.path`` before the fixtures are
imported into this conftest's namespace.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    admin_headers,
    api,
    approved_standing,
    build,
    initial_clock,
    insurance_analyst_headers,
    insured_contractor,
    statistics_analyst_headers,
    submitted_standing,
)
