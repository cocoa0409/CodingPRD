"""Shared pytest wiring for the orphan well plugging program suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.api_errors import install_error_status_map  # noqa: E402

install_error_status_map()


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()
