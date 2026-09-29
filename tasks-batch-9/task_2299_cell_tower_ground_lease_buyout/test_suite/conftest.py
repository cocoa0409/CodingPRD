"""Shared pytest fixtures for the lease-buyout suite.

The server is restarted with an empty store before every test, so no fixture here may
cache data across tests: each one hands back a client or a header set, and the composite
scenario builders in ``test_helpers.fixtures`` rebuild whatever state a test needs from
scratch through the public API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    api_client,
    make_acquisition_analyst_headers,
    make_approving_manager_headers,
    make_closing_manager_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_servicing_agent_headers,
    make_title_officer_headers,
    make_treasury_officer_headers,
)


@pytest.fixture
def api() -> ApiClient:
    """The API client, rooted at the base url the harness publishes."""
    return api_client


# ---------------------------------------------------------------------------
# Header sets for the seven roles whose user id carries no ownership meaning
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_headers():
    return make_platform_admin_headers()


@pytest.fixture
def analyst_headers():
    return make_acquisition_analyst_headers()


@pytest.fixture
def manager_headers():
    return make_portfolio_manager_headers()


@pytest.fixture
def approving_manager_headers():
    """The manager who approves valuations; distinct from the closing manager."""
    return make_approving_manager_headers()


@pytest.fixture
def closing_manager_headers():
    """The manager who closes deals; distinct from the approving manager."""
    return make_closing_manager_headers()


@pytest.fixture
def treasury_headers():
    return make_treasury_officer_headers()


@pytest.fixture
def title_headers():
    return make_title_officer_headers()


@pytest.fixture
def lender_headers():
    return make_lender_headers()


@pytest.fixture
def servicing_headers():
    return make_servicing_agent_headers()
