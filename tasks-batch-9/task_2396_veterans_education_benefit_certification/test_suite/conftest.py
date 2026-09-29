"""Pytest fixtures exposing the shared test infrastructure.

The runner owns the server lifecycle and restarts it with an empty database
before every test, so all fixtures here build their state through the public
API rather than assuming anything is already stored.
"""

import pytest

from test_helpers import VetEdApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401 — re-exported as pytest fixtures
    baseline,
    certified_certification,
    draft_certification,
    officials,
    priced_certification,
    submitted_certification,
)
from test_helpers.test_users import BURSAR_HEADERS, SAA_HEADERS, VA_HEADERS


@pytest.fixture(scope="session")
def api() -> VetEdApiClient:
    """Session-scoped API client; the runner manages the server lifecycle."""
    return api_client


@pytest.fixture
def bursar_headers():
    """The bursar's office identity, which the server never resolves to a row."""
    return BURSAR_HEADERS


@pytest.fixture
def saa_headers():
    """The state approving agency identity, which is opaque to the server."""
    return SAA_HEADERS


@pytest.fixture
def va_headers():
    """The VA processing office identity, which is opaque to the server."""
    return VA_HEADERS
