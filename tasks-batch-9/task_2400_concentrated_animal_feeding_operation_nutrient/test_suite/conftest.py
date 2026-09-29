"""Shared pytest configuration for the CAFO Nutrient Management API suite.

The harness restarts the server before every test, so each test observes an
empty database and the logical clock at its startup default. Nothing here
persists state between tests; the fixtures below only re-export the state
builders so tests can compose the state they need.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import api_client as _api_client  # noqa: E402
from test_helpers import fixtures as _fixtures  # noqa: E402


@pytest.fixture
def client():
    """The API client bound to the server under test."""
    return _api_client


@pytest.fixture
def scenario():
    """The canonical chain builder, callable with a stage and overrides."""
    return _fixtures.setup_scenario


@pytest.fixture
def ready_operation():
    """An approved plan with an active budget and a stocked lagoon."""
    return _fixtures.setup_ready_operation()
