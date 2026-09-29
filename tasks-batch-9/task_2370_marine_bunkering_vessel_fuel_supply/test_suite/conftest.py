"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle, `API_BASE_URL` and `PYTHONPATH`, so
`test_helpers` imports without any path manipulation here. Every test starts
against a freshly relaunched, empty database, so all preconditions are built from
scratch through the API by the builders in `test_helpers.fixtures`.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_coordinator_headers():
    """The bunker operations desk."""
    return TEST_USERS["ops_coordinator_headers"]


@pytest.fixture
def compliance_officer_headers():
    """The regulatory desk."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def surveyor_headers():
    """The independent surveyor."""
    return TEST_USERS["surveyor_headers"]


@pytest.fixture
def credit_controller_headers():
    """The credit and billing desk."""
    return TEST_USERS["credit_controller_headers"]


@pytest.fixture
def lab_technician_headers():
    """The testing laboratory."""
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def customer_rep_headers():
    """A buyer representative not bound to any particular customer record.

    Scope-gated calls must instead build headers from the real `Customer` id.
    """
    return TEST_USERS["customer_rep_headers"]


@pytest.fixture
def barge_master_headers():
    """A barge master not bound to any particular asset record.

    Assignment-gated calls must instead build headers from the real
    `DeliveryAsset` id.
    """
    return TEST_USERS["barge_master_headers"]
