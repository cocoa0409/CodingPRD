"""Shared pytest fixtures for the fire-staffing-overtime compliance suite."""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the running API under test."""
    return ApiClient()
