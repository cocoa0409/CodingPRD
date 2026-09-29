"""Pytest wiring for the Charity Golf Outing Operations API test suite.

The harness restarts the API server with an empty database before every single
test, so no fixture may assume state left behind by an earlier test.
"""

import sys
from pathlib import Path

import pytest

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers import (  # noqa: E402
    ApiClient,
    BENEFICIARY_HEADERS,
    COURSE_ALT_HEADERS,
    COURSE_HEADERS,
    DIRECTOR_ALT_HEADERS,
    DIRECTOR_HEADERS,
    SPONSORSHIP_ALT_HEADERS,
    SPONSORSHIP_HEADERS,
    TREASURER_ALT_HEADERS,
    TREASURER_HEADERS,
)


@pytest.fixture
def api() -> ApiClient:
    """Endpoint-aware client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def director_headers():
    return DIRECTOR_HEADERS


@pytest.fixture
def director_alt_headers():
    return DIRECTOR_ALT_HEADERS


@pytest.fixture
def sponsorship_headers():
    return SPONSORSHIP_HEADERS


@pytest.fixture
def sponsorship_alt_headers():
    return SPONSORSHIP_ALT_HEADERS


@pytest.fixture
def treasurer_headers():
    return TREASURER_HEADERS


@pytest.fixture
def treasurer_alt_headers():
    return TREASURER_ALT_HEADERS


@pytest.fixture
def course_headers():
    return COURSE_HEADERS


@pytest.fixture
def course_alt_headers():
    return COURSE_ALT_HEADERS


@pytest.fixture
def beneficiary_headers():
    return BENEFICIARY_HEADERS
