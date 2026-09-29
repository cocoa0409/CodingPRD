"""Shared pytest configuration for the battery-manufacturing API test suite.

Puts the task root on ``sys.path`` so ``test_helpers`` is importable, imports the
error-code module for its side effect of registering the error -> HTTP status map
with the validation framework, and re-exports the shared fixtures so every test
module sees them.
"""

import os
import sys

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.fixtures import (  # noqa: E402,F401
    World,
    admin_headers,
    api,
    assembly_world,
    fleet_headers,
    formation_world,
    make_world,
    shipped_unit_world,
    testing_world,
    warranty_headers,
    world,
)

__all__ = [
    "World",
    "admin_headers",
    "api",
    "assembly_world",
    "fleet_headers",
    "formation_world",
    "make_world",
    "shipped_unit_world",
    "testing_world",
    "warranty_headers",
    "world",
]
