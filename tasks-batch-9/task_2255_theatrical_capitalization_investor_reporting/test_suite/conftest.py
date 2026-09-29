"""
Pytest fixtures exposing the shared test infrastructure.

The server is already running and reachable at `API_BASE_URL` when these
fixtures are used, and its database is empty, so every fixture below builds the
state it needs from scratch through the documented endpoints.
"""

import pytest

from test_helpers import (
    COMPTROLLER2_HEADERS,
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM2_HEADERS,
    GM_HEADERS,
    PRODUCER2_HEADERS,
    PRODUCER_HEADERS,
    ApiClient,
    World,
    fixtures,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client pointed at the base URL the runner injected."""
    return ApiClient()


# ─── Role headers ─────────────────────────────────────────────────────────


@pytest.fixture()
def gm_headers():
    """The general management office operator `u-gm-1`."""
    return GM_HEADERS


@pytest.fixture()
def gm2_headers():
    """A second general management operator, `u-gm-2`."""
    return GM2_HEADERS


@pytest.fixture()
def comptroller_headers():
    """The production comptroller `u-ct-1`."""
    return COMPTROLLER_HEADERS


@pytest.fixture()
def comptroller2_headers():
    """A second comptroller, `u-ct-2`, for the duty-segregation pairs."""
    return COMPTROLLER2_HEADERS


@pytest.fixture()
def counsel_headers():
    """Syndication counsel `u-sc-1`."""
    return COUNSEL_HEADERS


@pytest.fixture()
def producer_headers():
    """The lead producer `u-lp-1`."""
    return PRODUCER_HEADERS


@pytest.fixture()
def producer2_headers():
    """A second lead producer, `u-lp-2`."""
    return PRODUCER2_HEADERS


# ─── Composite worlds ─────────────────────────────────────────────────────


@pytest.fixture()
def base(api: ApiClient) -> World:
    """A registered house plus a freshly opened production file."""
    return fixtures.base_world(api)


@pytest.fixture()
def budgeted(api: ApiClient) -> World:
    """A production file carrying one ACTIVE weekly operating budget."""
    world = fixtures.base_world(api)
    return fixtures.with_active_operating_budget(world)


@pytest.fixture()
def capitalized(api: ApiClient) -> World:
    """A production whose single accepted unit filled the target, then capitalized."""
    return fixtures.capitalized_world(api)


@pytest.fixture()
def running(api: ApiClient) -> World:
    """A capitalized production that has reached operating_status RUNNING."""
    return fixtures.running_world(api)


@pytest.fixture()
def certified_week(api: ApiClient) -> World:
    """A RUNNING production carrying exactly one CERTIFIED week."""
    return fixtures.certified_week_world(api)


@pytest.fixture()
def ledger(api: ApiClient) -> World:
    """The depth scenario: three royalty participants on the fixed-gross basis."""
    return fixtures.ledger_world(api)


@pytest.fixture()
def pool_ledger(api: ApiClient) -> World:
    """The depth scenario after the one-way conversion to a royalty pool."""
    return fixtures.ledger_world(api, pool_basis=True)
