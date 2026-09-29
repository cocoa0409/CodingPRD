"""Shared pytest configuration for the IPA capitation and risk pool suite."""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

# Importing the barrel also registers the error-id to HTTP-status map used by
# validate_error, so an error assertion cross-checks the status automatically.
from test_helpers import IpaApiClient  # noqa: E402


@pytest.fixture
def api() -> IpaApiClient:
    """A client bound to the API under test.

    The harness restarts the server before every test, so each test observes an
    empty database and builds all of its own preconditions.
    """
    return IpaApiClient()
