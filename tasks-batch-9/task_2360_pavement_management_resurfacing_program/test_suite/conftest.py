"""Shared pytest fixtures for the Pavement Management & Resurfacing Program suite.

Importing ``test_helpers`` registers the PRD's error-id to HTTP-status mapping,
so every ``validate_error`` call cross-checks the status code as well as the id.
"""

import pytest

import test_helpers  # noqa: F401  (registers the error/status mapping)
from test_helpers.api_client import PavementApiClient


@pytest.fixture
def api() -> PavementApiClient:
    """A client bound to the API under test."""
    return PavementApiClient()
