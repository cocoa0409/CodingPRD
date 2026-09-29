"""Shared fixtures for the camp accreditation and health compliance suite."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from test_helpers import (  # noqa: E402
    ApiClient,
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    STATE_AGENT_HEADERS,
)


@pytest.fixture
def api() -> ApiClient:
    """A client against the service under test, which starts with an empty store."""
    return ApiClient()


@pytest.fixture
def officer() -> dict:
    """The national office identity that opens cycles and confirms visits."""
    return OFFICER_ONE_HEADERS


@pytest.fixture
def second_officer() -> dict:
    """A second national office identity, free of the segregation-of-duties bar."""
    return OFFICER_TWO_HEADERS


@pytest.fixture
def state_agent() -> dict:
    """The state health department identity that moves the licensing axis."""
    return STATE_AGENT_HEADERS
