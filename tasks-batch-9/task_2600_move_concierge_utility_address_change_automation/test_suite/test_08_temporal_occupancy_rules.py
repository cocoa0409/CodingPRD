"""Three temporal resources, three different interval conventions.

A service window is half-open, so touching endpoints do not collide.  A
default-carrier territory interval is closed at both ends *and* demands a
clear day beyond it, so touching endpoints collide and so does the very next
day.  A postal forwarding period is closed at both ends with an aggregate
capacity of exactly one per resident, so a second redirection may only begin
after the first period's inclusive end.

Each rule is exercised on both sides of its boundary, and the occupancy count
is always derived by listing orders rather than read from any single field.
"""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    get_success_data,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.types import (
    ConsentGate,
    CreditStatus,
    DuplicateFlag,
    FilingStatus,
    MoveLifecycleStatus,
    ProvisionStatus,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Local derivation of the occupancy conserved quantity
# ---------------------------------------------------------------------------
def occupied_window_count(
    api: ApiClient, service_address_id: str, utility_type: str, headers: Dict[str, str]
) -> int:
    """Count the orders holding a window on one address and utility pairing.

    The count is derived from the order listing exactly as the PRD defines it:
    an order holds a window while its `provision_status` is `SCHEDULED` or
    `ACTIVE_SERVICE`.
    """
    orders = get_success_data(
        api.list_utility_orders(
            headers,
            service_address_id=service_address_id,
            utility_type=utility_type,
            limit=100,
        )
    )
    holding = {ProvisionStatus.SCHEDULED.value, ProvisionStatus.ACTIVE_SERVICE.value}
    return sum(1 for order in orders if order["provision_status"] in holding)


def _two_households_at_one_address(
    api, utility_types=None
) -> Dict[str, Any]:
    """Two mapped moves for different residents sharing one destination address.

    Both households are routed for the same commodity at the same destination,
    which is what puts their service orders on the same occupancy pairing of
    `service_address_id` and `utility_type`.
    """
    types = utility_types or [UtilityType.WATER.value]
    net = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    first = fixtures.mapped_move(api, network=net, utility_types=types)
    second_resident = fixtures.create_second_resident(api)
    second = fixtures.mapped_move(
        api, network={**net, "resident": second_resident}, utility_types=types
    )
    return {"network": net, "first": first, "second": second}


# ---------------------------------------------------------------------------
# Half-open service windows: touching endpoints are not a collision
# ---------------------------------------------------------------------------
def test_01_a_window_beginning_when_another_ends_is_accepted(api, ops_headers):
    """Back-to-back technician windows on one address both hold their slot.

    "The **occupancy rule**: the interval from `scheduled_window_start` up to
    but excluding `scheduled_window_end`" must not intersect another order's
    interval on the same pairing, so a window opening at exactly 13:00 against
    a neighbour closing at exactly 13:00 is admitted.  Both orders then hold a
    window, and the derived occupancy on that pairing is 2 — "Scheduling adds
    one; closure, provision failure, suspension and cancellation each release
    one."

    Design: Difficulty/resource_temporal_overlap/service_window_half_open_adjacency_allowed
    """
    setup = _two_households_at_one_address(api)
    address_id = setup["network"]["destination_address"]["id"]
    first_order = setup["first"]["orders_by_type"][UtilityType.WATER.value]
    second_order = setup["second"]["orders_by_type"][UtilityType.WATER.value]
    assert first_order["service_address_id"] == second_order["service_address_id"], (
        "both orders must sit on the same service address for the rule to engage"
    )

    morning = fixtures.schedule_order(
        api,
        first_order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )
    assert_order_dimensions(
        morning,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 1, "the first schedule must add exactly one occupied window"

    afternoon = fixtures.schedule_order(
        api,
        second_order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T13:00:00Z",
        scheduled_window_end="2026-08-05T17:00:00Z",
    )
    assert afternoon["provision_status"] == ProvisionStatus.SCHEDULED.value, (
        f"expected the adjacent window to be accepted, got {afternoon['provision_status']}"
    )
    assert afternoon["scheduled_window_start"] == morning["scheduled_window_end"], (
        "the accepted window must begin at exactly the instant the other ends"
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 2, "two adjacent half-open windows both hold their slot"


def test_02_a_window_overlapping_by_an_hour_is_refused(api, ops_headers):
    """One hour of genuine overlap collides on the same address and commodity.

    A second window running 12:00 through 16:00 intersects a neighbour holding
    09:00 through 13:00.  "Because the interval is half-open, a window that
    begins at exactly the instant another window ends does" not collide, but
    "genuine overlap is refused with `ERR_SERVICE_WINDOW_CONFLICT`".  This is the rejected side of the same
    boundary: the refused order keeps `provision_status` `DRAFT`, both window
    fields stay null, and the derived occupancy on the pairing stays at 1.

    Design: Difficulty/resource_temporal_overlap/service_window_half_open_adjacency_allowed
    """
    setup = _two_households_at_one_address(api)
    address_id = setup["network"]["destination_address"]["id"]
    first_order = setup["first"]["orders_by_type"][UtilityType.WATER.value]
    second_order = setup["second"]["orders_by_type"][UtilityType.WATER.value]

    fixtures.schedule_order(
        api,
        first_order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )

    assert_error(
        api.schedule_order(
            second_order["id"],
            f.schedule_payload(
                requested_service_date="2026-08-05",
                scheduled_window_start="2026-08-05T12:00:00Z",
                scheduled_window_end="2026-08-05T16:00:00Z",
            ),
            ops_headers,
        ),
        ApiErrorId.SERVICE_WINDOW_CONFLICT,
        expected_status=409,
    )

    refused = fixtures.read_order(api, second_order["id"])
    assert refused["provision_status"] == ProvisionStatus.DRAFT.value, (
        f"a refused schedule must leave the order in DRAFT, got {refused['provision_status']}"
    )
    assert refused["scheduled_window_start"] is None, (
        "a refused schedule must not write scheduled_window_start"
    )
    assert refused["scheduled_window_end"] is None, (
        "a refused schedule must not write scheduled_window_end"
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 1, "a refused schedule must not add an occupied window"


def test_03_identical_windows_on_different_commodities_do_not_collide(api, ops_headers):
    """The occupancy pairing is address and commodity, not the address alone.

    The rule reaches only "any other service order sharing this order's
    `service_address_id` and `utility_type` whose `provision_status` is
    `SCHEDULED` or `ACTIVE_SERVICE`", so a water appointment and an
    electric appointment may hold the very same instants at the same address.
    Each commodity keeps its own count of one.

    Design: Difficulty/resource_temporal_overlap/service_window_half_open_adjacency_allowed
    """
    setup = _two_households_at_one_address(
        api, utility_types=[UtilityType.WATER.value, UtilityType.ELECTRIC.value]
    )
    address_id = setup["network"]["destination_address"]["id"]
    water_order = setup["first"]["orders_by_type"][UtilityType.WATER.value]
    electric_order = setup["second"]["orders_by_type"][UtilityType.ELECTRIC.value]

    water = fixtures.schedule_order(
        api,
        water_order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )
    electric = fixtures.schedule_order(
        api,
        electric_order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )

    assert water["scheduled_window_start"] == electric["scheduled_window_start"], (
        "the two appointments must occupy the identical instants"
    )
    assert electric["provision_status"] == ProvisionStatus.SCHEDULED.value, (
        f"expected the electric order SCHEDULED, got {electric['provision_status']}"
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 1, "water occupancy at this address must be exactly one"
    assert occupied_window_count(
        api, address_id, UtilityType.ELECTRIC.value, ops_headers
    ) == 1, "electric occupancy at this address must be exactly one"


# ---------------------------------------------------------------------------
# Closed territory intervals demand a clear day between default carriers
# ---------------------------------------------------------------------------
def _default_carrier_through_june(api, admin_headers) -> Dict[str, Any]:
    """One default-carrier gas row covering 30303 from January through June."""
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)
    incumbent = fixtures.create_provider(api, f.gas_provider_payload())
    challenger = fixtures.create_provider(
        api, f.gas_provider_payload(name="Southern Gas Partners")
    )
    existing = assert_created(
        api.create_territory(
            f.territory_payload(
                incumbent["id"],
                postal_code="30303",
                state_code="GA",
                effective_from="2026-01-01",
                effective_to="2026-06-30",
                is_default_carrier=True,
                priority_rank=1,
            ),
            admin_headers,
        )
    )
    assert existing["effective_to"] == "2026-06-30", (
        f"expected the incumbent row to end 2026-06-30, got {existing['effective_to']}"
    )
    return {"incumbent": incumbent, "challenger": challenger, "existing": existing}


def test_04_a_default_carrier_starting_the_very_next_day_is_refused(api, admin_headers):
    """The day immediately after an inclusive end is still a collision.

    "for any one pairing of postal code and utility type, a new
    default-carrier row must begin at least one full day after the inclusive
    `effective_to` of every existing default-carrier row for that pairing",
    and the PRD spells out the counter-intuitive consequence: "Because both
    intervals are closed at each end, a new row starting on the day
    immediately after an existing row's `effective_to` is" still a conflict —
    "a clear day must separate them".  A row opening 2026-07-01 against an
    incumbent closing 2026-06-30 is therefore refused with
    `ERR_TERRITORY_OVERLAP`, and the coverage table still holds exactly one
    row for the pairing.

    Design: Difficulty/resource_temporal_overlap/territory_closed_interval_gap_buffer_rejected
    """
    setup = _default_carrier_through_june(api, admin_headers)

    assert_error(
        api.create_territory(
            f.territory_payload(
                setup["challenger"]["id"],
                postal_code="30303",
                state_code="GA",
                effective_from="2026-07-01",
                effective_to="2026-12-31",
                is_default_carrier=True,
                priority_rank=2,
            ),
            admin_headers,
        ),
        ApiErrorId.TERRITORY_OVERLAP,
        expected_status=409,
    )

    assert_page(
        api.list_territories(admin_headers, postal_code="30303", is_default_carrier=True), 1
    )


def test_05_a_default_carrier_starting_after_one_clear_day_is_accepted(api, admin_headers):
    """Leaving 2026-07-01 empty admits the successor row.

    With the incumbent's inclusive `effective_to` at 2026-06-30, a clear day
    of 2026-07-01 satisfies the requirement that the successor "begin at least
    one full day after the inclusive `effective_to`".  This is the accepted
    side of the same boundary the previous case rejects: the successor is
    created and the pairing then carries two default-carrier rows.

    Design: Difficulty/resource_temporal_overlap/territory_closed_interval_gap_buffer_rejected
    """
    setup = _default_carrier_through_june(api, admin_headers)

    successor = assert_created(
        api.create_territory(
            f.territory_payload(
                setup["challenger"]["id"],
                postal_code="30303",
                state_code="GA",
                effective_from="2026-07-02",
                effective_to="2026-12-31",
                is_default_carrier=True,
                priority_rank=2,
            ),
            admin_headers,
        )
    )
    assert successor["effective_from"] == "2026-07-02", (
        f"expected the successor to begin 2026-07-02, got {successor['effective_from']}"
    )
    assert successor["is_default_carrier"] is True, (
        "the successor must be registered as a default carrier"
    )

    assert_page(
        api.list_territories(admin_headers, postal_code="30303", is_default_carrier=True), 2
    )


def test_06_a_non_default_row_may_open_inside_the_buffer_day(api, admin_headers):
    """The spacing rule binds default carriers only.

    "Non-default rows carry no such restriction and may overlap each other
    freely", so the very `effective_from` of 2026-07-01 that was refused for a
    default carrier is accepted for an ordinary row — and so is a row that
    overlaps the incumbent outright.  The pairing still reports one
    default-carrier row.

    Design: Difficulty/resource_temporal_overlap/territory_closed_interval_gap_buffer_rejected
    """
    setup = _default_carrier_through_june(api, admin_headers)

    buffer_day_row = assert_created(
        api.create_territory(
            f.territory_payload(
                setup["challenger"]["id"],
                postal_code="30303",
                state_code="GA",
                effective_from="2026-07-01",
                effective_to="2026-12-31",
                is_default_carrier=False,
                priority_rank=2,
            ),
            admin_headers,
        )
    )
    assert buffer_day_row["is_default_carrier"] is False, (
        "the accepted row must not be a default carrier"
    )
    assert buffer_day_row["effective_from"] == "2026-07-01", (
        f"expected 2026-07-01, got {buffer_day_row['effective_from']}"
    )

    overlapping_row = assert_created(
        api.create_territory(
            f.territory_payload(
                setup["challenger"]["id"],
                postal_code="30303",
                state_code="GA",
                effective_from="2026-03-01",
                effective_to="2026-09-30",
                is_default_carrier=False,
                priority_rank=3,
            ),
            admin_headers,
        )
    )
    assert overlapping_row["effective_from"] == "2026-03-01", (
        "a non-default row may sit squarely inside the incumbent's interval"
    )

    assert_page(
        api.list_territories(admin_headers, postal_code="30303", is_default_carrier=True), 1
    )
    assert_page(
        api.list_territories(admin_headers, postal_code="30303", is_default_carrier=False), 2
    )


# ---------------------------------------------------------------------------
# One active forwarding period per resident, closed at both ends
# ---------------------------------------------------------------------------
def _resident_holding_one_forwarding_period(api) -> Dict[str, Any]:
    """One resident, two moves, and a submitted year-long redirection on the first.

    The capacity is aggregated on the resident rather than on the move, so the
    second redirection has to be attempted from a second move of the same
    household — here a move to a different destination so the two are not read
    as one another's duplicate.
    """
    net = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    other_destination = fixtures.create_address(api, f.third_address_payload())
    first = fixtures.verified_move(api, network=net)

    second_move = fixtures.ingest_move(
        api,
        {**net, "destination_address": other_destination},
        move_date="2026-08-20",
    )
    assert_move_state(second_move, duplicate_flag=DuplicateFlag.NONE.value)
    fixtures.pass_identity_by_kba(api, second_move["id"])
    second_move = fixtures.read_move(api, second_move["id"])
    assert_move_state(
        second_move,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        consent_gate=ConsentGate.OPEN.value,
    )

    filing = fixtures.draft_filing(api, first["move"]["id"], forward_start_date="2026-08-20")
    assert filing["forward_end_date"] == "2027-08-19", (
        f"expected a forward_end_date of 2027-08-19, got {filing['forward_end_date']}"
    )
    filing = fixtures.submit_filing(api, filing["id"])
    assert filing["status"] == FilingStatus.SUBMITTED.value, (
        f"expected the first redirection SUBMITTED, got {filing['status']}"
    )
    return {
        "network": net,
        "first": first,
        "second_move": second_move,
        "held_filing": filing,
    }


def test_07_a_second_period_touching_the_first_inclusive_end_is_refused(api, ops_headers):
    """Sharing a single day with a live redirection is already an intersection.

    "the resident may have no other filing in `SUBMITTED` or `CONFIRMED` whose
    closed period from `forward_start_date` through `forward_end_date`
    intersects the period being submitted".  The held period runs 2026-08-20
    through its inclusive end of 2027-08-19, so a second period opening on
    2027-08-19 shares exactly that one day: "Because each period spans a full
    year and the aggregate capacity per resident is exactly one, a second
    overlapping redirection is refused with `ERR_FORWARDING_PERIOD_CONFLICT`".
    The refused filing stays `DRAFT` and the resident still holds one
    submitted redirection.

    Design: Difficulty/resource_temporal_overlap/forwarding_period_aggregate_capacity_one_active
    """
    setup = _resident_holding_one_forwarding_period(api)
    resident_id = setup["network"]["resident"]["id"]

    clashing = fixtures.draft_filing(
        api, setup["second_move"]["id"], forward_start_date="2027-08-19"
    )
    assert clashing["forward_end_date"] == "2028-08-17", (
        f"expected a forward_end_date of 2028-08-17, got {clashing['forward_end_date']}"
    )

    assert_error(
        api.submit_filing(clashing["id"], {}, ops_headers),
        ApiErrorId.FORWARDING_PERIOD_CONFLICT,
        expected_status=409,
    )

    refused = get_success_data(api.get_filing(clashing["id"], ops_headers))
    assert refused["status"] == FilingStatus.DRAFT.value, (
        f"a refused submission must leave the filing in DRAFT, got {refused['status']}"
    )
    assert refused["submitted_by_user_id"] is None, (
        "a refused submission must not stamp submitted_by_user_id"
    )
    assert_page(
        api.list_filings(
            ops_headers, resident_id=resident_id, status=FilingStatus.SUBMITTED.value
        ),
        1,
    )


def test_08_a_second_period_beginning_the_day_after_is_accepted(api, ops_headers):
    """Opening one day later clears the closed interval entirely.

    "a period that begins after a prior period's inclusive end is accepted",
    so a redirection opening on 2027-08-20 — the day after the held period's
    inclusive end of 2027-08-19 — is admitted and derives its own inclusive
    end of 2028-08-18 from "`forward_start_date` plus the standard 365-day
    forwarding term minus one day".  This is the accepted side of the same
    boundary: the resident now holds two non-intersecting submitted periods,
    and the second move's readiness reaches 62 once its filing component
    "lifts the move's readiness filing component to 60".

    Design: Difficulty/resource_temporal_overlap/forwarding_period_aggregate_capacity_one_active
    """
    setup = _resident_holding_one_forwarding_period(api)
    resident_id = setup["network"]["resident"]["id"]
    second_move_id = setup["second_move"]["id"]

    successor = fixtures.draft_filing(
        api, second_move_id, forward_start_date="2027-08-20"
    )
    assert successor["forward_end_date"] == "2028-08-18", (
        f"expected a forward_end_date of 2028-08-18, got {successor['forward_end_date']}"
    )

    submitted = assert_ok(api.submit_filing(successor["id"], {}, ops_headers))
    assert submitted["status"] == FilingStatus.SUBMITTED.value, (
        f"expected the successor redirection SUBMITTED, got {submitted['status']}"
    )
    assert submitted["forward_start_date"] == "2027-08-20", (
        "the accepted period must begin the day after the held period's inclusive end"
    )

    assert_page(
        api.list_filings(
            ops_headers, resident_id=resident_id, status=FilingStatus.SUBMITTED.value
        ),
        2,
    )
    assert_move_state(
        fixtures.read_move(api, second_move_id),
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        readiness_score=62,
    )
