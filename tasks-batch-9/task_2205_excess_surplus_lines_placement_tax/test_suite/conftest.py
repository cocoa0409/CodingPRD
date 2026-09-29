"""Pytest configuration for the Surplus Lines Placement Tax API test suite.

The task directory is placed on ``sys.path`` so that ``test_helpers`` imports
resolve, and the layered composite fixtures are re-exported here so every test
module can request them by name.
"""

import os
import sys

TASK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_DIR not in sys.path:
    sys.path.insert(0, TASK_DIR)

from test_helpers.fixtures import (  # noqa: E402,F401
    affidavit_world,
    affixed_world,
    api,
    approved_carrier_world,
    ca_home_world,
    calculated_world,
    configured_world,
    endorsed_world,
    nv_home_world,
    placement_world,
    policy_world,
    searched_world,
    stamping_submitted_world,
    white_listed_world,
    world,
)
