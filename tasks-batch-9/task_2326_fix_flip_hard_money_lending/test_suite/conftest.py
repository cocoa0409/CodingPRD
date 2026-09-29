"""Shared pytest configuration for the lending suite.

The harness restarts the API server before every individual test, so every test
sees an empty database and the logical clock at its declared default of
`2026-08-01T00:00:00Z`. Fixtures therefore build all state from scratch.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client as _api_client  # noqa: E402
from test_helpers import fixtures as _fixtures  # noqa: E402


@pytest.fixture
def api():
    """The shared API client."""
    return _api_client


@pytest.fixture
def clock():
    """Move the logical clock; returns the new `current_utc`."""
    return _fixtures.set_clock


@pytest.fixture
def closed_loan():
    """The canonical three-line origination closed into a live loan."""
    return _fixtures.build_closed_loan()


@pytest.fixture
def sized_application():
    """The canonical three-line origination taken through sizing."""
    return _fixtures.build_sized_application()


@pytest.fixture
def origination():
    """Sponsor, property, trades, application and approved scope lines."""
    return _fixtures.build_origination()
