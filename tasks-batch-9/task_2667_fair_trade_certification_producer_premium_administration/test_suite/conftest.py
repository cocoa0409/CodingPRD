"""Pytest configuration for the Fair Trade Certification API compliance suite.

The suite is executed against a live server that the harness restarts, with an
empty database, before every single test. Every fixture therefore builds its
world from scratch through the endpoints the PRD declares.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

import test_helpers  # noqa: F401,E402  (registers the error id to HTTP status map)
from test_helpers.fixtures import *  # noqa: F401,F403,E402
