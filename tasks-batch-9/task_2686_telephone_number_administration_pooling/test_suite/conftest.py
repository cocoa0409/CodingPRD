"""Shared pytest configuration for the telephone number administration suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database and builds every precondition it needs.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The domain API client, pre-bound to the /numbering prefix."""
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    """Role header sets for the five actor roles."""
    return TEST_USERS
