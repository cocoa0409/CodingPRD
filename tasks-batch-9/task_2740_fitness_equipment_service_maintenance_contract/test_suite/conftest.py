"""
Pytest bridge for the FleetCare test suite.

Puts the task root on ``sys.path`` so ``test_helpers`` imports cleanly no matter which
directory pytest was invoked from, and re-exports the shared fixtures so every test
module can request ``api``, ``admin``, ``coordinator`` and ``planner`` by name.
"""

import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers.fixtures import (  # noqa: E402,F401
    admin,
    api,
    coordinator,
    planner,
)
