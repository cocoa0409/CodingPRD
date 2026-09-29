"""Pytest wiring for the shared test infrastructure.

The harness restarts the API server before every individual test, so each test
below starts against an empty database and builds every precondition it needs
through the declared endpoints.
"""

from __future__ import annotations

import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client; the server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def state_authority_headers():
    return make_state_authority_headers()


@pytest.fixture
def program_coordinator_headers():
    return make_program_coordinator_headers()


@pytest.fixture
def registrar_headers():
    return make_registrar_headers()


@pytest.fixture
def instructor_headers():
    return make_instructor_headers()
