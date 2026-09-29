"""Shared test configuration for the PPP availability payment suite."""
import pytest

from test_helpers import api_client as shared_api_client


@pytest.fixture
def client():
    """The API client bound to the base URL the harness published."""
    return shared_api_client
