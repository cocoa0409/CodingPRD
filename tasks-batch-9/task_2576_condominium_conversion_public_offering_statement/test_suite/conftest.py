"""Shared pytest wiring for the condominium conversion registry suite.

The runner relaunches the API server before every test, so each test builds all
of its own state from an empty database through the public API. Nothing is
cached across tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import api  # noqa: E402,F401  (pytest fixture)
