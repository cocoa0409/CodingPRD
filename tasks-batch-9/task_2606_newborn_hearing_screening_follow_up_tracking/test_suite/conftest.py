"""Shared pytest fixtures for the test suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: F401,E402  (registers the error status map)
from test_helpers.api_client import EhdiApiClient  # noqa: E402
from test_helpers import fixtures  # noqa: E402


@pytest.fixture
def client() -> EhdiApiClient:
    """A client bound to the server under test."""
    return EhdiApiClient()


@pytest.fixture
def registry(client: EhdiApiClient) -> fixtures.Registry:
    """The standard cast of facilities and providers in region R1."""
    return fixtures.base_registry(client)
