"""Shared pytest configuration for the subscription retention API suite.

The runner launches the API server and exports ``API_BASE_URL`` before pytest
starts, and it restarts the server before each individual test, so every test
below opens against an empty database and a logical clock reading its documented
initial value.  Nothing here creates data; the only job of this module is to make
``test_helpers`` importable no matter which directory pytest was invoked from.
"""

import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))
