"""Shared pytest fixtures for the compliance API suite.

The service under test is relaunched before each individual test, so every test
begins against an empty database and a logical clock reading its startup value.
Nothing is shared between tests beyond the HTTP client itself.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """An HTTP client pointed at the service under test."""
    return ApiClient()
