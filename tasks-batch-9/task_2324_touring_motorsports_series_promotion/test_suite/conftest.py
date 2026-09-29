"""Pytest fixtures exposing the test helpers.

Header fixtures come in two shapes. The four opaque roles get a ready-made
header dictionary, because their identity is a fixed string. The three
entity-backed roles — venue manager, competitor team and sponsor representative —
get a builder instead, because their identity is the id of the row they own and
that id only exists once the row has been created.

The composite state fixtures are thin wrappers that call the setup helpers with
their default arguments. Tests that need a different shape of state call the
helper directly with keyword overrides.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, constants
from test_helpers import fixtures as helpers
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Client and clock
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def logical_clock(api: ApiClient) -> Iterator[str]:
    """Put the logical clock back to its default reading before every test.

    All time-dependent behaviour reads the logical clock, so a test that moves it
    would otherwise leak that instant into the next test's lead-time, selling
    window and staging window checks.
    """
    yield helpers.reset_clock(api)


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


@pytest.fixture
def test_users() -> Dict[str, Dict[str, str]]:
    """The identity of each role, keyed by role name."""
    return TEST_USERS


@pytest.fixture
def promoter_headers() -> Dict[str, str]:
    """Headers for the series promoter."""
    return users.make_series_promoter_headers()


@pytest.fixture
def ticketing_headers() -> Dict[str, str]:
    """Headers for the ticketing manager."""
    return users.make_ticketing_manager_headers()


@pytest.fixture
def safety_official_headers() -> Dict[str, str]:
    """Headers for a safety official, defaulting to the plan author."""
    return users.make_safety_official_headers()


@pytest.fixture
def safety_author_headers() -> Dict[str, str]:
    """Headers for the safety official who authors and submits plans."""
    return users.make_safety_author_headers()


@pytest.fixture
def safety_certifier_headers() -> Dict[str, str]:
    """Headers for the second safety official, who certifies or returns a plan."""
    return users.make_safety_certifier_headers()


@pytest.fixture
def safety_inspector_headers() -> Dict[str, str]:
    """Headers for the safety official who files technical inspections."""
    return users.make_safety_inspector_headers()


@pytest.fixture
def finance_controller_headers() -> Dict[str, str]:
    """Headers for a finance controller, defaulting to the settlement preparer."""
    return users.make_finance_controller_headers()


@pytest.fixture
def finance_preparer_headers() -> Dict[str, str]:
    """Headers for the finance controller who prepares settlements."""
    return users.make_finance_preparer_headers()


@pytest.fixture
def finance_approver_headers() -> Dict[str, str]:
    """Headers for the second finance controller, who approves settlements."""
    return users.make_finance_approver_headers()


@pytest.fixture
def anonymous_headers() -> Dict[str, str]:
    """Headers carrying no identity at all."""
    return users.make_headers_without_identity()


@pytest.fixture
def venue_manager_headers() -> Callable[[str], Dict[str, str]]:
    """Builder for venue manager headers, taking the managed venue's id."""
    return users.make_venue_manager_headers


@pytest.fixture
def competitor_team_headers() -> Callable[[str], Dict[str, str]]:
    """Builder for competitor team headers, taking the team's competitor id."""
    return users.make_competitor_team_headers


@pytest.fixture
def sponsor_rep_headers() -> Callable[[str], Dict[str, str]]:
    """Builder for sponsor representative headers, taking the sponsor's id."""
    return users.make_sponsor_rep_headers


# ---------------------------------------------------------------------------
# Tier 1 state
# ---------------------------------------------------------------------------


@pytest.fixture
def season(api: ApiClient) -> Dict[str, Any]:
    """A season in planning with the canonical calendar, cooldown and budget."""
    return helpers.create_season(api)


@pytest.fixture
def venue(api: ApiClient) -> Dict[str, Any]:
    """A registered building in the primary market."""
    return helpers.create_venue(api)


@pytest.fixture
def competitor(api: ApiClient) -> Dict[str, Any]:
    """A registered competing team."""
    return helpers.create_competitor(api)


@pytest.fixture
def sponsor(api: ApiClient) -> Dict[str, Any]:
    """A registered sponsor holding category exclusivity."""
    return helpers.create_sponsor(api)


# ---------------------------------------------------------------------------
# Tier 2 and 3 state
# ---------------------------------------------------------------------------


@pytest.fixture
def proposed_booking(api: ApiClient) -> Dict[str, Any]:
    """A booking at the opening negotiation state."""
    return helpers.proposed_booking(api)


@pytest.fixture
def countered_booking(api: ApiClient) -> Dict[str, Any]:
    """A booking the building has countered."""
    return helpers.countered_booking(api)


@pytest.fixture
def confirmed_booking(api: ApiClient) -> Dict[str, Any]:
    """An accepted booking and the tour stop it synthesized."""
    return helpers.confirmed_booking(api)


@pytest.fixture
def stop_with_show_timing(api: ApiClient) -> Dict[str, Any]:
    """A confirmed stop whose show timing and pit party terms are set."""
    return helpers.stop_with_show_timing(api)


# ---------------------------------------------------------------------------
# Tier 4 and 5 state
# ---------------------------------------------------------------------------


@pytest.fixture
def stop_ready_for_sale(api: ApiClient) -> Dict[str, Any]:
    """A stop that satisfies every readiness condition but is not yet on sale."""
    return helpers.stop_ready_for_sale(api)


@pytest.fixture
def stop_on_sale(api: ApiClient) -> Dict[str, Any]:
    """A stop whose sales window has been opened."""
    return helpers.stop_on_sale(api)


@pytest.fixture
def stop_with_pending_order(api: ApiClient) -> Dict[str, Any]:
    """An on-sale stop carrying one unpaid order."""
    return helpers.stop_with_pending_order(api)


@pytest.fixture
def stop_with_paid_order(api: ApiClient) -> Dict[str, Any]:
    """An on-sale stop carrying one settled order."""
    return helpers.stop_with_paid_order(api)


@pytest.fixture
def stop_sales_halted(api: ApiClient) -> Dict[str, Any]:
    """A stop halted by the loss of its last committed marketing money."""
    return helpers.stop_sales_halted(api)


@pytest.fixture
def stop_sales_closed(api: ApiClient) -> Dict[str, Any]:
    """A stop with a settled order whose sales window has been closed."""
    return helpers.stop_sales_closed(api)


@pytest.fixture
def settlement_ready_stop(api: ApiClient) -> Dict[str, Any]:
    """A closed stop carrying every money source, ready for a settlement."""
    return helpers.settlement_ready_stop(api)


@pytest.fixture
def prepared_settlement(api: ApiClient) -> Dict[str, Any]:
    """A settlement cut under the provisional variant."""
    return helpers.prepared_settlement(api)


@pytest.fixture
def disputed_settlement(api: ApiClient) -> Dict[str, Any]:
    """A prepared settlement the building has pushed back on."""
    return helpers.disputed_settlement(api)


@pytest.fixture
def approved_settlement(api: ApiClient) -> Dict[str, Any]:
    """An approved settlement, its stop settled and its season rolled up."""
    return helpers.approved_settlement(api)


@pytest.fixture
def multi_market_season(api: ApiClient) -> Dict[str, Any]:
    """One season with two settled stops in different markets."""
    return helpers.multi_market_season(api, market_count=2, settle=True)


@pytest.fixture
def transport_chain_stops(api: ApiClient) -> Dict[str, Any]:
    """Two stops in one season, the second linked to the first as predecessor."""
    return helpers.transport_chain_stops(api)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


@pytest.fixture
def clock_default() -> str:
    """The instant the logical clock reads before it has ever been set."""
    return constants.CLOCK_DEFAULT_UTC
