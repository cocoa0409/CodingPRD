"""Suite-wide fixtures.

Every test runs against an empty database, so nothing is seeded here: the
``client`` fixture hands out a fresh HTTP client and each test composes exactly
the state it needs from the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def client() -> ApiClient:
    """An HTTP client pointed at the service under test."""
    return ApiClient()
