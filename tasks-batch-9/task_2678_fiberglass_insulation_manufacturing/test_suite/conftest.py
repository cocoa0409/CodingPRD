"""Shared pytest fixtures for the Fiberglass Insulation Manufacturing suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the error/status map)
from test_helpers.api_client import InsulationApiClient  # noqa: E402


@pytest.fixture
def client() -> InsulationApiClient:
    """A client bound to the server under test."""
    return InsulationApiClient()
