"""Pytest wiring for the roadside inspection data review API test suite.

The harness restarts the API server before every individual test, so the database
is empty at the start of each one.  Fixtures therefore build all preconditions
through the PRD-declared endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    AUDITOR_ALICE,
    AUDITOR_BOB,
    AUDITOR_CAROL,
    AUDITOR_DAVE,
    REVIEW_OFFICER_ID,
    STATE_OFFICER_ID,
    STATE_OFFICER_ID_2,
    make_auditor_headers,
    make_review_officer_headers,
    make_state_officer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """HTTP client bound to the API under test."""
    return ApiClient(os.environ.get("API_BASE_URL"))


@pytest.fixture
def auditor():
    """Headers for the auditor who owns reference data and the scoring epoch."""
    return make_auditor_headers(AUDITOR_ALICE)


@pytest.fixture
def auditor_bob():
    return make_auditor_headers(AUDITOR_BOB)


@pytest.fixture
def auditor_carol():
    return make_auditor_headers(AUDITOR_CAROL)


@pytest.fixture
def auditor_dave():
    return make_auditor_headers(AUDITOR_DAVE)


@pytest.fixture
def officer():
    return make_state_officer_headers(STATE_OFFICER_ID)


@pytest.fixture
def officer_two():
    return make_state_officer_headers(STATE_OFFICER_ID_2)


@pytest.fixture
def reviewer():
    return make_review_officer_headers(REVIEW_OFFICER_ID)


@pytest.fixture
def clock(api):
    """Pin the logical clock to its declared start before the test body runs."""
    fx.set_clock(api)
    return fx


@pytest.fixture
def medium_carrier(api, clock):
    """A MEDIUM carrier (20 power units, 1,600,000 VMT, exposure 30.0)."""
    return fx.create_carrier(api)


@pytest.fixture
def scored_report(api):
    """One carrier, one UNSAFE_DRIVING weight-5 code, one threshold and a SCORED
    report holding a single violation."""
    return fx.build_single_violation_scored_report(api)
