"""Pytest configuration for the HOA Declarant Turnover compliance suite.

Puts the task directory on ``sys.path`` so ``test_helpers`` imports cleanly no
matter where pytest is invoked from, and re-exports the shared fixtures.

The API under test is restarted against an empty database before every
individual test, so every fixture here is function-scoped and builds its own
preconditions through the endpoints the PRD declares.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers import (  # noqa: E402,F401
    admin_headers,
    api,
    association,
    association_with_case,
    auditor_headers,
    committee_headers,
    conveyed_component,
    declarant_headers,
    inspector_headers,
)
