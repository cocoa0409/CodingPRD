"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def bank_admin_headers():
    return TEST_USERS["bank_admin_headers"]


@pytest.fixture
def implementer_headers():
    return TEST_USERS["implementer_headers"]


@pytest.fixture
def activator_headers():
    return TEST_USERS["activator_headers"]


@pytest.fixture
def lockbox_op_headers():
    return TEST_USERS["lockbox_op_headers"]


@pytest.fixture
def lockbox_op2_headers():
    return TEST_USERS["lockbox_op2_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def billing_approver_headers():
    return TEST_USERS["billing_approver_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def customer_operator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_operator_headers"]
