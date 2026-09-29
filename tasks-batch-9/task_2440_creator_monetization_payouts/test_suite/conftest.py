"""Shared pytest configuration for the compliance suite."""

import os
import sys

import pytest

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers import api_errors  # noqa: F401,E402  registers status mapping
from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.fixtures import *  # noqa: F401,F403,E402


@pytest.fixture
def api():
    """A client bound to the service under test."""
    return ApiClient()
