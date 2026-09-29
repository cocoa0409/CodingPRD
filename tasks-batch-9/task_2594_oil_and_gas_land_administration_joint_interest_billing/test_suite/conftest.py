"""Shared pytest wiring for the land administration and JIB test suite.

The harness restarts the service before every individual test, so each test
begins against an empty store and builds every precondition it needs through
the public API.  Nothing here caches state between tests.
"""

import os
import sys

import pytest

# The helper package sits beside this directory at the task root.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApiClient, api_client  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture()
def api() -> ApiClient:
    """The API client every test drives the service through."""
    return api_client


@pytest.fixture()
def land_admin_headers() -> dict:
    return TEST_USERS["land_administrator_headers"]


@pytest.fixture()
def jib_accountant_headers() -> dict:
    return TEST_USERS["joint_interest_accountant_headers"]


@pytest.fixture()
def audit_reviewer_headers() -> dict:
    return TEST_USERS["audit_reviewer_headers"]


@pytest.fixture()
def second_audit_reviewer_headers() -> dict:
    return TEST_USERS["second_audit_reviewer_headers"]


@pytest.fixture()
def compliance_officer_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]
