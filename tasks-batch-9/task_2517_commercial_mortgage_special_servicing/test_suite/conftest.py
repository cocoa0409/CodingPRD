"""Shared pytest fixtures for the CMBS Special Servicing API test suite.

The harness restarts the API server before every test, so each test begins
against an empty database and builds its own preconditions through the
endpoints the PRD declares.
"""

import pytest

from test_helpers.api_client import SpecialServicingClient


@pytest.fixture
def api() -> SpecialServicingClient:
    """A client bound to the running service under test."""
    return SpecialServicingClient()
