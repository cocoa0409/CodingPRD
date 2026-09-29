"""Shared pytest configuration for the production music library test suite.

The service is relaunched against an empty database before every test, so each
test builds its own preconditions through the declared endpoints. The composite
builders and fixtures live in `test_helpers.fixtures` and are re-exported here.
"""

import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers.fixtures import *  # noqa: E402,F401,F403
