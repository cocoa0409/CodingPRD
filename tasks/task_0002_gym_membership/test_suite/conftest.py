"""Pytest fixtures exposing test_helpers infrastructure.

PYTHONPATH is set by prd-bench-local-runner so `test_helpers` resolves without any
sys.path hacks. Server lifecycle is also the runner's job — this file only wires up
lightweight fixtures and role headers.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset server state and clock between tests so each test starts from a
    clean baseline. Some test-driving capabilities (clock-advance, FAIL/SUCCESS
    payment cascades) mutate global server state, and the runner does not
    restart the impl container between tests, so we reset via the test-harness
    /_test/reset endpoint.
    """
    api_client._request("POST", "/_test/reset", headers=TEST_USERS["billing_admin_headers"])
    yield


# ──────────────────────────────────────────────────────────
# Shared-constant role headers — for tests that do NOT exercise ownership.
# Ownership-gated tests build headers via make_<role>_headers(<actual-id>) directly.
# ──────────────────────────────────────────────────────────

@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]
