"""Shared pytest fixtures for the QDRO Processing API suite.

The harness restarts the API against an empty database before each test, so no
fixture here cleans up: every test builds the rows it needs and then reads them
back through the declared endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import QdroApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN_HEADERS,
    ANALYST_HEADERS,
)


@pytest.fixture
def client():
    """An HTTP client pointed at the API under test."""
    return QdroApiClient()


@pytest.fixture
def admin():
    """Headers for the plan's fiduciary operator."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def analyst():
    """Headers for the reviewer."""
    return dict(ANALYST_HEADERS)
