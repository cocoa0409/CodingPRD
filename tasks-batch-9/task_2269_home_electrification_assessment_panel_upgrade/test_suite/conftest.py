"""Shared pytest configuration for the Home Electrification Rebates suite.

The runner relaunches the service before every test, so each test observes an
empty database and builds its own preconditions.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    approved_project_world,
    assessment_world,
    contractor_world,
    household_world,
    installed_project_world,
    open_program_world,
    paid_project_world,
    project_world,
    reserved_project_world,
    scheduled_inspection_world,
    verified_project_world,
)
