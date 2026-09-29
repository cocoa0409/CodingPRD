"""Shared pytest wiring for the EMD protocol QA compliance suite."""

import os
import sys

import pytest

# Make the sibling test_helpers package importable regardless of how pytest was
# invoked.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test.

    The harness restarts the server before each test, so every test begins with
    an empty database and the logical clock at its startup value.
    """
    return ApiClient()
