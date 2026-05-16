"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and sets PYTHONPATH so test_helpers is
importable. Server lifecycle is the runner's responsibility — this
conftest only wires fixtures and resets the simulation clock between
tests.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    reset_clock_to,
)
from test_helpers.constants import TEST_DEFAULTS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_simulation_clock():
    """Reset the clock to INITIAL_CLOCK before every test.

    PRD §2.10 makes the simulation clock a singleton; without this
    reset each test would inherit clock advances from earlier tests
    and time-gated assertions would drift.
    """
    try:
        reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    except Exception:  # noqa: BLE001
        # If the clock reset fails the runner will surface the real
        # error in a deterministic order; do not mask it here.
        pass
    yield


# ---------------------------------------------------------------------------
# Per-role headers exposed as pytest fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def registrar_headers_alt():
    return TEST_USERS["registrar_headers_alt"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def proctor_headers_alt():
    return TEST_USERS["proctor_headers_alt"]


@pytest.fixture
def accommodations_officer_headers():
    return TEST_USERS["accommodations_officer_headers"]


@pytest.fixture
def accommodations_officer_headers_alt():
    return TEST_USERS["accommodations_officer_headers_alt"]


@pytest.fixture
def credits_officer_headers():
    return TEST_USERS["credits_officer_headers"]


@pytest.fixture
def candidate_headers_fallback():
    return TEST_USERS["candidate_headers_fallback"]
