"""Pytest configuration for the Corporate Meal Stipend API suite.

The server lifecycle, the API base URL and the database reset between tests are
owned by the harness, so this module only makes ``test_helpers`` importable when
the suite is invoked from inside ``test_suite/``.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)
