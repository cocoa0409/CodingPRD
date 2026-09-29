"""Shared pytest fixtures for the Cloud Cost Allocation & Chargeback suite.

The harness relaunches the API with an empty store before every individual
test, so no fixture here caches state: each one hands back a client or a header
map and every test builds the world it needs from PRD-declared endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ADMIN_HEADERS,
    ANALYST_ALT_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_HEADERS,
    NO_AUTH_HEADERS,
    ApiClient,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture()
def analyst():
    return ANALYST_HEADERS


@pytest.fixture()
def analyst_alt():
    return ANALYST_ALT_HEADERS


@pytest.fixture()
def controller():
    return CONTROLLER_HEADERS


@pytest.fixture()
def controller_alt():
    return CONTROLLER_ALT_HEADERS


@pytest.fixture()
def admin():
    return ADMIN_HEADERS


@pytest.fixture()
def anonymous():
    """Headers carrying neither `X-User-ID` nor `X-User-Role`."""
    return NO_AUTH_HEADERS
