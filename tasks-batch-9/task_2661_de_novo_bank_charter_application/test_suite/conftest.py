"""
Shared pytest wiring for the De Novo Bank Charter Application test suite.

The harness restarts the service before every individual test, so each test
begins against an empty database with the logical clock at its startup value of
2026-08-01T00:00:00Z. Every fixture therefore builds the state it needs from
scratch, through the same public endpoints a real charter project would call.
"""

import os
import sys

import pytest

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import DeNovoApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api():
    """A client speaking to the service mounted under /de-novo."""
    return DeNovoApiClient()


# ---------------------------------------------------------------------------
# Group and organizer worlds
# ---------------------------------------------------------------------------
@pytest.fixture
def open_group(api):
    return fx.open_group(api)


@pytest.fixture
def four_seat_group(api):
    return fx.seated_group(api, seats=4, clear=True)


@pytest.fixture
def composition_met_group(api):
    return fx.composition_met_group(api)


@pytest.fixture
def second_group(api):
    return fx.second_group(api)


# ---------------------------------------------------------------------------
# Plan, raise, filing and pre-opening worlds
# ---------------------------------------------------------------------------
@pytest.fixture
def submitted_plan_group(api):
    return fx.submitted_plan_group(api)


@pytest.fixture
def boundary_plan_group(api):
    return fx.boundary_plan_group(api)


@pytest.fixture
def filing_ready_group(api):
    return fx.filing_ready_group(api)


@pytest.fixture
def escrow_ready_group(api):
    return fx.escrow_ready_group(api)


@pytest.fixture
def conditionally_approved_group(api):
    return fx.conditionally_approved_group(api)


@pytest.fixture
def pre_opening_group(api):
    return fx.pre_opening_group(api)


@pytest.fixture
def passed_exam_group(api):
    return fx.passed_exam_group(api)


@pytest.fixture
def deficient_exam_group(api):
    return fx.deficient_exam_group(api)


@pytest.fixture
def opened_bank(api):
    return fx.opened_bank(api)
