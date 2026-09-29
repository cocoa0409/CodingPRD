"""Shared pytest fixtures for the Speakers Bureau Engagements API suite.

The server is restarted before every individual test, so each test starts
against an empty database and a logical clock sitting at its startup value of
``2026-08-01T00:00:00Z``.  Every precondition a test needs is therefore built
from scratch through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_admin_headers,
    make_agent_headers,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture()
def admin_headers() -> dict:
    """Headers for the back-office BureauAdmin operator."""
    return make_admin_headers()


@pytest.fixture()
def agent_headers() -> dict:
    """Headers for the deal-desk BookingAgent who owns the inquiries."""
    return make_agent_headers()
