"""
Shared pytest configuration for the compliance suite.

The API server is restarted before every individual test, so each test starts
against an empty database with the logical clock back at its start instant and
must build every precondition it needs through the declared endpoints.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

# Importing the helper package registers the error-id to HTTP-status mapping the
# framework's error validator consults.
import test_helpers  # noqa: E402,F401
from test_helpers.fixtures import api  # noqa: E402,F401
