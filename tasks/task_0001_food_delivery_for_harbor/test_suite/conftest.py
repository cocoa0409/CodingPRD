"""Pytest fixtures exposing test_helpers infrastructure.

PYTHONPATH is set by prd-bench-local-runner so `test_helpers` resolves without any
sys.path hacks. Server lifecycle is also the runner's job — this file only wires up
lightweight fixtures and role headers.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


# ──────────────────────────────────────────────────────────
# Shared-constant role headers — for tests that do NOT exercise ownership.
# Ownership-gated tests construct headers via make_<role>_headers(<actual-id>) directly.
# ──────────────────────────────────────────────────────────

@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def cs_headers():
    return TEST_USERS["cs_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def restaurant_headers():
    return TEST_USERS["restaurant_headers"]


@pytest.fixture
def rider_headers():
    return TEST_USERS["rider_headers"]
