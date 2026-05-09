"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; this module only
exposes test_helpers as pytest fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


# --- Per-role shared-constant fixtures (canonical for opaque roles per PRD §2.1) ---

@pytest.fixture
def claims_admin_headers():
    return TEST_USERS["claims_admin_headers"]


@pytest.fixture
def policy_admin_headers():
    return TEST_USERS["policy_admin_headers"]


@pytest.fixture
def claims_reviewer_headers():
    return TEST_USERS["claims_reviewer_headers"]


@pytest.fixture
def claims_approver_headers():
    return TEST_USERS["claims_approver_headers"]


@pytest.fixture
def batch_approver_headers():
    return TEST_USERS["batch_approver_headers"]


@pytest.fixture
def batch_executor_headers():
    return TEST_USERS["batch_executor_headers"]


@pytest.fixture
def payout_operator_headers():
    return TEST_USERS["payout_operator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
