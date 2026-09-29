"""Shared pytest fixtures for the Employer Tuition Benefit Administration suite."""

import sys
from pathlib import Path

import pytest

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers import TuitionBenefitApiClient  # noqa: E402


@pytest.fixture
def api() -> TuitionBenefitApiClient:
    """A client pointed at the service under test."""
    return TuitionBenefitApiClient()
