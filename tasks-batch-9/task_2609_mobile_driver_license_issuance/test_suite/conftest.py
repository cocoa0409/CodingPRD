"""Shared pytest configuration for the mDL issuance compliance suite.

The server is relaunched before every individual test, so each test starts
against an empty database and builds all of its state through the published
endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import MdlApiClient  # noqa: E402
from test_helpers.fixtures import *  # noqa: E402,F401,F403  (composite builders)


@pytest.fixture
def api() -> MdlApiClient:
    """A client pointed at the API under test."""
    return MdlApiClient()
