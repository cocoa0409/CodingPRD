"""Shared pytest fixtures for the dependent eligibility audit suite."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, Builder  # noqa: E402
from test_helpers.fixtures import ORIGIN_INSTANT  # noqa: E402


@pytest.fixture()
def client() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture()
def b(client: ApiClient) -> Builder:
    """A precondition builder over the client."""
    return Builder(client)


@pytest.fixture()
def clock(b: Builder) -> str:
    """Pins the logical clock to the instant every scenario is written against."""
    b.set_clock(ORIGIN_INSTANT)
    return ORIGIN_INSTANT
