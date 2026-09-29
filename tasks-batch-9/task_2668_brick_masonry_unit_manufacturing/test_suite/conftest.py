"""
Shared pytest wiring for the brick and masonry unit manufacturing test suite.

The harness restarts the API server before every individual test, so each test
starts against an empty database and every fixture below is function scoped and
builds the state it needs through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def clock(api) -> str:
    """
    Pin the logical clock to its startup default.

    Every date-sensitive expectation in this suite is measured from
    2026-08-01T00:00:00Z.
    """
    return fx.set_clock(api, "2026-08-01T00:00:00Z")


@pytest.fixture
def plant_env(api, clock):
    """
    One active plant with two pits, a qualified 50/50 body, a kiln and a car.

    The body blends a 50 percent clay pit with a 50 percent shale pit, which puts
    the absorption index at exactly 8.00 and the durability grade at SW.
    """
    return fx.build_plant_with_assets(api, clock=None)


@pytest.fixture
def fired_lot_env(api, clock):
    """
    The production chain driven all the way to one ON_COLOR fired lot.

    The lot is fired at the five-position kiln's centreline, so its colour index
    is 52.18 and it carries 9600 fired units.
    """
    return fx.build_fired_lot(api, clock=None)
