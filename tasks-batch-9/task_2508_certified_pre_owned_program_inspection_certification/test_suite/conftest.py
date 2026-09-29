"""Pytest wiring for the Certified Pre-Owned Programme suite.

Every fixture the suite uses is defined in `test_helpers.fixtures`; importing
them here registers them for all test modules, including the autouse fixture
that returns the logical clock to `2026-08-01T00:00:00Z` before each test.
"""

from test_helpers.fixtures import *  # noqa: F401,F403
