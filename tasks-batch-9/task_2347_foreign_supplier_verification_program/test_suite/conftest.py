"""Shared pytest fixtures for the FSVP compliance suite.

The harness restarts the API before every individual test, so each test sees an
empty database. Fixtures therefore build every precondition they need through
documented endpoints.
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
def clock_at_base(api: ApiClient) -> str:
    """Pin the logical clock to the instant the suite reasons from."""
    fx.set_clock(api, fx.CLOCK_BASE)
    return fx.CLOCK_BASE


@pytest.fixture
def importer(api: ApiClient, clock_at_base: str) -> dict:
    """A registered importer with no qualified individual yet."""
    return fx.create_importer(api)


@pytest.fixture
def base_program(api: ApiClient):
    """Importer, two designated individuals, approved supplier, food, pair."""
    return fx.base_program(api)


@pytest.fixture
def analyzed_program(api: ApiClient):
    """A pair whose hazard analysis is APPROVED (Listeria 13.80, Salmonella 17.25)."""
    return fx.analyzed_program(api)


@pytest.fixture
def verified_program(api: ApiClient):
    """A pair whose verification approval has been signed."""
    return fx.verified_program(api)
