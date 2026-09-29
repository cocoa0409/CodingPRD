"""Shared pytest configuration for the certificate authority compliance suite.

The service under test is started by the harness and reset before every single
test, so each test may assume an empty store and the default logical clock.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401 - re-exported as fixtures
    _error_status_map,
    api,
    client,
    dv_environment,
    ev_environment,
)
