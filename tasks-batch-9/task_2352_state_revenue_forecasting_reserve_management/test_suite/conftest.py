"""Shared pytest fixtures for the compliance suite."""

import os
import sys
from typing import Dict

import pytest

# The task directory holds `test_helpers/` alongside `test_suite/`.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import ApiClient  # noqa: E402
from test_helpers import test_users as U  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def director_headers() -> Dict[str, str]:
    return U.make_director_headers()


@pytest.fixture
def exec_economist_headers() -> Dict[str, str]:
    return U.make_exec_economist_headers()


@pytest.fixture
def leg_economist_headers() -> Dict[str, str]:
    return U.make_leg_economist_headers()


@pytest.fixture
def treasurer_headers() -> Dict[str, str]:
    return U.make_treasurer_headers()


@pytest.fixture
def voter_headers() -> Dict[str, str]:
    return U.make_voter_headers()


@pytest.fixture
def rating_analyst_headers() -> Dict[str, str]:
    return U.make_rating_analyst_headers()
