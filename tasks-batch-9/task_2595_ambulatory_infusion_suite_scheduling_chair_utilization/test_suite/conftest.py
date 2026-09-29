"""Pytest fixtures exposing the shared test helpers to every test module."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    AUTH_SPECIALIST,
    MEDICAL_DIRECTOR,
    PHARMACIST,
    SCHEDULER,
)


@pytest.fixture
def api():
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def scheduler_headers():
    return SCHEDULER


@pytest.fixture
def pharmacist_headers():
    return PHARMACIST


@pytest.fixture
def auth_specialist_headers():
    return AUTH_SPECIALIST


@pytest.fixture
def medical_director_headers():
    return MEDICAL_DIRECTOR
