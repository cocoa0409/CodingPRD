"""
Shared pytest fixtures for the Student Loan Repayment Match Benefit suite.

The harness restarts the API and its database before every individual test, so
each test begins against an empty ledger with the logical clock reading its
declared starting instant.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402,F401


@pytest.fixture
def client() -> ApiClient:
    """A typed API client bound to the base URL under test."""
    return ApiClient()
