"""Pytest wiring: exposes the helper layer as fixtures.

The harness restarts the service with an empty database before every test, so the
client is safe to share for the whole session while all state a test needs is
built inside the test itself.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The API client, one method per declared endpoint."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["project_coordinator_headers"]


@pytest.fixture
def second_coordinator_headers():
    return TEST_USERS["second_project_coordinator_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def second_technician_headers():
    return TEST_USERS["second_field_technician_headers"]


@pytest.fixture
def lsp_drafter_headers():
    return TEST_USERS["lsp_drafter_headers"]


@pytest.fixture
def lsp_signer_headers():
    return TEST_USERS["lsp_signer_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def lab_analyst_headers():
    """Placeholder laboratory identity: usable only where ownership is not reached."""
    return TEST_USERS["lab_analyst_headers"]


@pytest.fixture
def homeowner_headers():
    """Placeholder property identity: usable only where ownership is not reached."""
    return TEST_USERS["homeowner_headers"]
