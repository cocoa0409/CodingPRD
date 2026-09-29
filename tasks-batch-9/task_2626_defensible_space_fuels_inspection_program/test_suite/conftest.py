"""Shared pytest configuration for the fire-district test suite.

The harness restarts the service before each individual test, so every test
begins against an empty district whose logical clock sits at its initial value.
No test may therefore depend on rows created by another test.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

# Registering the error/status map happens on import of test_helpers.api_errors,
# which the fixtures module pulls in transitively.
from test_helpers.fixtures import client  # noqa: E402,F401
