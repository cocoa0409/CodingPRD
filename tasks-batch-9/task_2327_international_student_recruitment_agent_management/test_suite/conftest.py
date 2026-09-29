"""Shared pytest wiring for the recruitment-agent management suite.

The harness restarts the server before every individual test, so each test sees
an empty store and a logical clock parked at the mandated default.  Nothing is
shared between tests: every fixture below builds its state from scratch through
the published endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import RecruitmentApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture()
def client() -> RecruitmentApiClient:
    """A client pointed at the server under test."""
    return RecruitmentApiClient()


@pytest.fixture()
def active_partner(client: RecruitmentApiClient) -> dict:
    """A cleared agency with an ACTIVE contract, one rate card and a territory."""
    return fx.build_active_partner(client)
