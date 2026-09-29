"""Shared pytest configuration for the Fair Access Plan test suite.

The suite is run from the task directory, so ``test_helpers`` is importable as a
top-level package; the ``sys.path`` insertion below makes that true even when
pytest is invoked from somewhere else.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

# Registers the error-id to HTTP-status mapping used by validate_error.
from test_helpers import api_errors  # noqa: E402,F401

# Re-exported so every test module sees the shared fixtures.
from test_helpers.fixtures import (  # noqa: E402,F401
    admin,
    bindable_application,
    bound_policy,
    client,
    clock_pinned,
    foundations,
    in_force_policy,
    members,
    roomy_foundations,
)
