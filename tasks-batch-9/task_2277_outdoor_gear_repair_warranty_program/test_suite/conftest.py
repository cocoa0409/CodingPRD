"""Pytest bridge: expose every fixture defined in test_helpers.fixtures.

The harness restarts the API server before each individual test, so every
fixture below rebuilds its preconditions from scratch through the endpoints
the PRD declares.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import *  # noqa: F401,F403,E402
