"""Shared pytest fixtures for the Trade Show Exhibitor Sales suite."""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def client() -> ApiClient:
    """A client bound to the base URL the harness exports for this test."""
    return ApiClient()
