"""Pytest configuration for the Restaurant Brand Standards Audit API suite.

The harness starts the API server and relaunches it before every individual
test, so each test begins against an empty database and builds its own
preconditions through the public endpoints.
"""
import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)
