"""Shared pytest fixtures for the corporate renewable PPA origination suite.

The harness restarts the API server before every test, so each test observes an
empty database and a logical clock reading 2026-08-01T00:00:00Z.  Nothing here
caches state across tests.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER,
    DEAL_COMMITTEE,
    ORIGINATOR,
    REGISTRY_AGENT,
    SETTLEMENT_ANALYST,
)


@pytest.fixture
def api():
    """The API client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def originator_headers():
    """The developer-side origination lead."""
    return ORIGINATOR


@pytest.fixture
def credit_officer_headers():
    """The underwriter, who owns every credit decision."""
    return CREDIT_OFFICER


@pytest.fixture
def deal_committee_headers():
    """The signing authority."""
    return DEAL_COMMITTEE


@pytest.fixture
def settlement_analyst_headers():
    """The operator who runs the settlement ledger."""
    return SETTLEMENT_ANALYST


@pytest.fixture
def registry_agent_headers():
    """The environmental attribute registry operator."""
    return REGISTRY_AGENT
