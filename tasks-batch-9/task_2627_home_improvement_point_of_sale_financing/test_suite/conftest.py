"""Pytest fixtures exposing the shared test infrastructure.

The harness restarts the server and empties its store before every test, so the
API client is function-scoped: each test gets a fresh HTTP session against a
freshly booted server with an empty database and the clock at its default
instant of `2026-08-01T00:00:00Z`.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ANALYST_HEADERS,
    SECOND_AGENT_HEADERS,
    SECOND_ANALYST_HEADERS,
    SECOND_UNDERWRITER_HEADERS,
    UNDERWRITER_HEADERS,
)


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    """`ProgramAdmin` operator headers."""
    return ADMIN_HEADERS


@pytest.fixture
def underwriter_headers():
    """`ProgramUnderwriter` operator headers."""
    return UNDERWRITER_HEADERS


@pytest.fixture
def second_underwriter_headers():
    """A different `ProgramUnderwriter` operator."""
    return SECOND_UNDERWRITER_HEADERS


@pytest.fixture
def analyst_headers():
    """`RiskAnalyst` operator headers."""
    return ANALYST_HEADERS


@pytest.fixture
def second_analyst_headers():
    """A different `RiskAnalyst` operator."""
    return SECOND_ANALYST_HEADERS


@pytest.fixture
def agent_headers():
    """`ServicingAgent` operator headers."""
    return AGENT_HEADERS


@pytest.fixture
def second_agent_headers():
    """A different `ServicingAgent` operator."""
    return SECOND_AGENT_HEADERS
