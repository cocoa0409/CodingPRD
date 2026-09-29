"""Shared pytest fixtures.

The server under test is already running; each test sees a fresh, empty
database, so all state is created inside the test through PRD endpoints.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401
from test_helpers.api_client import QualityControlApiClient  # noqa: E402
from test_helpers.constants import DEFAULT_CLOCK  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_committee_headers,
    make_system_admin_headers,
)


@pytest.fixture
def api() -> QualityControlApiClient:
    return QualityControlApiClient()


@pytest.fixture
def admin_headers():
    return make_system_admin_headers()


@pytest.fixture
def committee_headers():
    return make_committee_headers()


@pytest.fixture
def default_clock():
    return DEFAULT_CLOCK
