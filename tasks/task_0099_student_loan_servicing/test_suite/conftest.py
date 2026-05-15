"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and sets PYTHONPATH so test_helpers is
importable. Server lifecycle is the runner's responsibility — this
conftest only wires fixtures.
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
    """Reset the clock to the initial value before every test.

    PRD §2.6 makes the simulation clock a singleton; without this
    reset each test would inherit clock advances from earlier tests
    and time-gated assertions would drift.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    yield


# Per-role headers exposed as pytest fixtures.
@pytest.fixture
def servicer_admin_headers():
    return TEST_USERS["servicer_admin_headers"]


@pytest.fixture
def servicer_admin_headers_alt():
    return TEST_USERS["servicer_admin_headers_alt"]


@pytest.fixture
def servicer_certifier_headers():
    return TEST_USERS["servicer_certifier_headers"]


@pytest.fixture
def servicer_certifier_headers_alt():
    return TEST_USERS["servicer_certifier_headers_alt"]


@pytest.fixture
def servicer_approver_headers():
    return TEST_USERS["servicer_approver_headers"]


@pytest.fixture
def servicer_approver_headers_alt():
    return TEST_USERS["servicer_approver_headers_alt"]


@pytest.fixture
def collections_officer_headers():
    return TEST_USERS["collections_officer_headers"]


@pytest.fixture
def borrower_headers_fallback():
    return TEST_USERS["borrower_headers_fallback"]


@pytest.fixture
def system_test_headers():
    return TEST_USERS["system_test_headers"]
