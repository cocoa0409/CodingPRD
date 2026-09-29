"""Shared pytest wiring for the In-Bond Movement & Bonded Carrier suite.

The server is already running when these tests execute and every test gets a
fresh, empty database, so each test builds its own preconditions through the
API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing the error catalogue registers each error identifier's HTTP status,
# so validate_error() can check the status code without restating it.
from test_helpers import api_errors  # noqa: E402,F401
from test_helpers.api_client import InBondApiClient  # noqa: E402


@pytest.fixture
def client() -> InBondApiClient:
    """A client pointed at the running API."""
    return InBondApiClient()
