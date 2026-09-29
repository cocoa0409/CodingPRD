"""Shared pytest fixtures for the release-of-information compliance suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import RoiApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the error/HTTP map)
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> RoiApiClient:
    """A client against the API under test.

    The harness restarts the server before every test, so each test starts
    against an empty database and builds its own preconditions.
    """
    return RoiApiClient()


@pytest.fixture
def clock(api: RoiApiClient):
    """The logical clock pinned to the suite's canonical starting instant."""
    fx.set_clock(api)
    return api


@pytest.fixture
def base(api: RoiApiClient):
    """Clock, CA fee rule, one facility, one patient."""
    return fx.base_world(api)


@pytest.fixture
def third_party(api: RoiApiClient):
    """base plus an ATTORNEY requesting party holding one GENERAL_MEDICAL authorization."""
    return fx.third_party_world(api)


@pytest.fixture
def patient_access(api: RoiApiClient):
    """base plus a PATIENT requesting party linked to that patient."""
    return fx.patient_access_world(api)
