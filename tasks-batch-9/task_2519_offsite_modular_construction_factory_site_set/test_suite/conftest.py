"""Shared pytest configuration for the offsite modular construction test suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import ModularApiClient  # noqa: E402


@pytest.fixture
def api() -> ModularApiClient:
    """A client pointed at the API under test.

    The harness restarts the server before every test, so each test opens onto
    an empty database and builds its own preconditions through the API.
    """
    return ModularApiClient()
