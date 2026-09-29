"""Shared pytest fixtures for the Nonprofit Newsroom Funding API suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database with the logical clock reading exactly
2026-08-01T00:00:00Z. Every fixture therefore builds its preconditions from
scratch through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    CLOCK_EPOCH,
    TEST_USERS,
    api_client,
    make_member_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client, one instance for the whole session."""
    return api_client


@pytest.fixture
def development_officer_headers():
    """Fundraising staff: builds tiers, enrols members, cultivates funders."""
    return TEST_USERS["development_officer_headers"]


@pytest.fixture
def second_development_officer_headers():
    """A second fundraising identity, for the dual-control pairs of the funding
    chain where the accepting officer may not be the soliciting officer."""
    return TEST_USERS["development_officer_2_headers"]


@pytest.fixture
def editorial_director_headers():
    """Newsroom editorial leadership and owner of the independence firewall."""
    return TEST_USERS["editorial_director_headers"]


@pytest.fixture
def second_editorial_director_headers():
    """A second editorial identity, for rulings that must not be filed by the
    director who attested the disclosure."""
    return TEST_USERS["editorial_director_2_headers"]


@pytest.fixture
def finance_controller_headers():
    """Finance staff: periods, settlement, refunds, releases, report review."""
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def board_oversight_headers():
    """Board-level oversight: ratifications and documented overrides."""
    return TEST_USERS["board_oversight_headers"]


@pytest.fixture
def member_headers():
    """Headers for a Member caller. X-User-ID is the id of the acting member
    row, so ownership-gated calls pass the member's own id."""
    return make_member_headers


@pytest.fixture
def clock_epoch():
    """The logical clock's value on a fresh server."""
    return CLOCK_EPOCH
