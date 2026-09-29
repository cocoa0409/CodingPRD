"""Shared pytest fixtures for the PRD compliance suite.

The server lifecycle is owned by the harness; these fixtures only build clients
and actor headers. Every test runs against a freshly started, empty server, so
each test builds its own preconditions through documented endpoints.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    AnnexationApiClient,
    boundary_commissioner_headers,
    county_assessor_headers,
    fiscal_analyst_headers,
    register_error_status_map,
    state_law_admin_headers,
)

# Teach the framework validators the documented HTTP status of every error id.
register_error_status_map()


@pytest.fixture
def api() -> AnnexationApiClient:
    """The typed API client bound to the running server.

    Function-scoped on purpose: every test runs against a freshly started
    server, so a client (and its underlying connection pool) must not outlive
    the process it was talking to.
    """
    return AnnexationApiClient()


@pytest.fixture
def state_law_admin():
    """Headers for a StateLawAdmin — an opaque operator identifier."""
    return state_law_admin_headers()


@pytest.fixture
def fiscal_analyst():
    """Headers for a FiscalAnalyst — an opaque operator identifier."""
    return fiscal_analyst_headers()


@pytest.fixture
def boundary_commissioner():
    """Headers for a BoundaryCommissioner — an opaque operator identifier."""
    return boundary_commissioner_headers()


@pytest.fixture
def county_assessor():
    """Headers for a CountyAssessor — an opaque operator identifier."""
    return county_assessor_headers()
