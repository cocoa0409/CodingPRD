"""Shared pytest fixtures for the Premium Sports Hospitality Packages suite.

Every test runs against a freshly restarted server with an empty database, so
each fixture below builds its preconditions from scratch through the endpoints
the PRD declares.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    bronze_floor,
    clock,
    event,
    exposed_floor,
    gold_floor,
)
