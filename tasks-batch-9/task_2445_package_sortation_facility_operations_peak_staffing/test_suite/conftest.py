"""Shared pytest configuration for the Package Sortation Peak Staffing suite.

The harness relaunches the API server before every individual test, so each test
starts against an empty database and every fixture below builds its own state
from scratch through the documented endpoints.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401  (pytest collects these)
    api,
    facility,
    world,
)
