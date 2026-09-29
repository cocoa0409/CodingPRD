"""Shared pytest fixtures.

Each test runs against a freshly started server with an empty database, so every
scenario is rebuilt from scratch through the documented endpoints.  The logical
clock is pinned to its documented starting instant at the top of every test so
that notice periods, blackout windows and term intervals are deterministic.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.fixtures import (
    Ctx,
    setup_adopted_ips,
    setup_approved_replacement,
    setup_breach_quarter,
    setup_committee,
    setup_executed_replacement,
    setup_finalized_quarter,
    setup_full_menu,
    setup_governed_plan,
    setup_noticed_replacement,
    setup_qdia_candidates,
    setup_submitted_replacement,
)


@pytest.fixture
def api() -> ApiClient:
    """An HTTP client bound to the runner-provided base URL."""
    return ApiClient()


@pytest.fixture(autouse=True)
def pinned_clock(api: ApiClient):
    """Pin the logical UTC clock to 2026-08-01T00:00:00Z before each test."""
    api.set_clock(DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def committee(api: ApiClient) -> Ctx:
    """A registered plan with three activated voting members, charter still
    DRAFT."""
    return setup_committee(api)


@pytest.fixture
def governed_plan(api: ApiClient) -> Ctx:
    """A plan whose charter is ADOPTED."""
    return setup_governed_plan(api)


@pytest.fixture
def adopted_ips(api: ApiClient) -> Ctx:
    """A governed plan with one ADOPTED policy statement and an OPEN posture."""
    return setup_adopted_ips(api)


@pytest.fixture
def full_menu(api: ApiClient) -> Ctx:
    """Five seated CORE slots out of a six-slot capacity."""
    return setup_full_menu(api)


@pytest.fixture
def finalized_quarter(api: ApiClient) -> Ctx:
    """Quarter 0 finalized with every fund CLEAR."""
    return setup_finalized_quarter(api)


@pytest.fixture
def breach_quarter(api: ApiClient) -> Ctx:
    """Quarter 0 scored with two breaching funds, presented and minuted but not
    yet finalized."""
    return setup_breach_quarter(api)


@pytest.fixture
def breach_quarter_finalized(api: ApiClient) -> Ctx:
    """The same breaching quarter, finalized: two of five slots AT_RISK, a ratio
    of 0.4000 and a RESTRICTED posture."""
    return setup_breach_quarter(api, finalize=True)


@pytest.fixture
def submitted_replacement(api: ApiClient) -> Ctx:
    """One replacement proposal in UNDER_REVIEW."""
    return setup_submitted_replacement(api)


@pytest.fixture
def approved_replacement(api: ApiClient) -> Ctx:
    """One APPROVED proposal holding a reserved menu position."""
    return setup_approved_replacement(api)


@pytest.fixture
def noticed_replacement(api: ApiClient) -> Ctx:
    """One NOTICE_ISSUED proposal with a reserved blackout window."""
    return setup_noticed_replacement(api)


@pytest.fixture
def executed_replacement(api: ApiClient) -> Ctx:
    """One EXECUTED proposal, clock inside the blackout window."""
    return setup_executed_replacement(api)


@pytest.fixture
def qdia_candidates(api: ApiClient) -> Ctx:
    """A seated menu plus an empty QDIA slot and four candidate suites."""
    return setup_qdia_candidates(api)
