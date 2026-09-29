"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def second_program_admin_headers():
    return TEST_USERS["second_program_admin_headers"]


@pytest.fixture
def loyalty_analyst_headers():
    return TEST_USERS["loyalty_analyst_headers"]


@pytest.fixture
def second_loyalty_analyst_headers():
    return TEST_USERS["second_loyalty_analyst_headers"]


@pytest.fixture
def loyalty_supervisor_headers():
    return TEST_USERS["loyalty_supervisor_headers"]


@pytest.fixture
def second_loyalty_supervisor_headers():
    return TEST_USERS["second_loyalty_supervisor_headers"]


@pytest.fixture
def store_operator_headers():
    """Placeholder `StoreOperator` identity — safe only where ownership is not
    under test; ownership-gated calls must use `make_store_operator_headers`."""
    return TEST_USERS["store_operator_headers"]


@pytest.fixture
def pump_terminal_headers():
    """Placeholder `PumpTerminal` identity — see `store_operator_headers`."""
    return TEST_USERS["pump_terminal_headers"]


@pytest.fixture
def settlement_clerk_headers():
    """Placeholder `SettlementClerk` identity — see `store_operator_headers`."""
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def member_headers():
    """Placeholder `Member` identity — see `store_operator_headers`."""
    return TEST_USERS["member_headers"]
