"""Endpoint-shape probes: list pages, action calls, sweeps and computed reads.

Each collection pages and filters on the keys the contract declares and nothing
else; each action endpoint carries an empty body and takes everything it needs
from server state; the rollover sweep is one cross-fixture call that reports what
it changed; the margin report changes nothing at all; and one path with one
optional field selects between two completely different postponement behaviours.
"""

from typing import Any, Dict

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_REQUEST,
    FINANCE_CONTROLLER,
    RIGHTS_MANAGER,
    ApiClient,
    add_component,
    allocate_booking,
    approve_build,
    assert_daily_run_report,
    assert_list_page,
    assert_margin_report,
    assert_package_pricing,
    assert_total_count,
    cancel_booking,
    daily_run,
    get_success_data,
    ids_of,
    installments_of,
    make_block,
    make_booking,
    make_bronze_package,
    make_build,
    make_client,
    make_committed_deal,
    make_event,
    make_published_bronze_package,
    make_tranche,
    price_package,
    publish_package,
    read_block,
    read_booking,
    read_event,
    release_deal,
    reset_clock,
    set_clock,
    validate_error,
)


def _published_bronze_fixture(api: ApiClient) -> Dict[str, Any]:
    """A fixture whose forty contracted ticket units are all released.

    A published package needs ticket supply standing behind it, and releasing the
    whole contract also leaves the fixture unexposed, so a five-unit CORPORATE
    sale on it nets 558720 with no guarantee surcharge.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)
    release_deal(api, deal["id"], 40)
    package = make_published_bronze_package(api, event["id"])
    return {"event": event, "deal": deal, "package": package}


def _four_bookings_across_two_buyers(api: ApiClient) -> Dict[str, Any]:
    """Three sales to one buyer — the third cancelled — and one to another.

    Every declared booking filter therefore narrows the same base set of four to a
    different, checkable count.
    """
    scenario = _published_bronze_fixture(api)
    package_id = scenario["package"]["id"]
    buyer = make_client(api, name="Northbridge Capital", client_type="CORPORATE")
    other = make_client(api, name="Vantage Partners", client_type="TRAVEL_PARTNER")

    first = make_booking(api, buyer["id"], package_id, channel="CORPORATE", units=5)
    second = make_booking(api, buyer["id"], package_id, channel="CORPORATE", units=5)
    third = make_booking(api, buyer["id"], package_id, channel="CORPORATE", units=5)
    cancel_booking(api, third["id"])
    fourth = make_booking(api, other["id"], package_id, channel="CORPORATE", units=5)

    scenario.update({"buyer": buyer, "other": other, "first": first,
                     "second": second, "third": third, "fourth": fourth})
    return scenario


# --------------------------------------------------------------------------
# Paging and filtering a collection
# --------------------------------------------------------------------------


def test_the_booking_list_pages_in_creation_order_and_counts_the_whole_set(
    api: ApiClient,
) -> None:
    """Two pages of two, then an empty third page that still counts four.

    Rows come back oldest first, so the two pages partition the four sales in
    creation order and `has_more` flips off on the second rather than staying
    constant. Skipping past the end returns no rows at all while the counter
    still describes the whole matching set, which is what makes the metadata a
    property of the query rather than of the page.

    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts every record matching the filter before the page window is applied."

    Design: Corner/endpoints/list_endpoints_page_and_filter_on_their_declared_keys_only
    """
    scenario = _four_bookings_across_two_buyers(api)

    page_one = assert_list_page(
        api.list_bookings(FINANCE_CONTROLLER, {"limit": 2, "offset": 0}),
        expected_total=4, expected_rows=2, expected_limit=2, expected_offset=0,
        expected_has_more=True,
    )
    assert ids_of(page_one) == [scenario["first"]["id"], scenario["second"]["id"]]

    page_two = assert_list_page(
        api.list_bookings(FINANCE_CONTROLLER, {"limit": 2, "offset": 2}),
        expected_total=4, expected_rows=2, expected_limit=2, expected_offset=2,
        expected_has_more=False,
    )
    assert ids_of(page_two) == [scenario["third"]["id"], scenario["fourth"]["id"]]

    assert_list_page(
        api.list_bookings(FINANCE_CONTROLLER, {"limit": 2, "offset": 4}),
        expected_total=4, expected_rows=0, expected_limit=2, expected_offset=4,
        expected_has_more=False,
    )


def test_the_booking_list_narrows_on_its_declared_client_and_status_filters(
    api: ApiClient,
) -> None:
    """Each declared filter cuts the four sales down to the one row it describes.

    Filtering on the buyer returns only that buyer's single sale, and filtering on
    the delivery dimension returns only the cancelled one. Both counters fall to
    1, so the filter really is applied to the set rather than to the page.

    PRD §2.3: "Beyond `limit` and `offset`, list endpoints expose filters that make every stored relationship reverse-reachable — the deal list filters on `event_id`, `deal_status` and `inventory_type`; the tranche list on `rights_deal_id` and `tranche_state`; the allocation-block list on `rights_deal_id`, `channel` and `block_state`; the package list on `event_id`, `package_status` and `tier`; the component list on `package_product_id` and `component_type`; the booking list on `client_id`, `package_product_id`, `allocation_block_id`, `fulfillment_status` and `payment_status`; the installment list on `booking_id`, `installment_state` and `installment_kind`; the build list on `event_id`, `build_state` and `zone_code`; and the host-assignment list on `on_site_host_id`, `booking_id`, `hospitality_build_id` and `assignment_state`."

    Design: Corner/endpoints/list_endpoints_page_and_filter_on_their_declared_keys_only
    """
    scenario = _four_bookings_across_two_buyers(api)

    by_client = assert_list_page(
        api.list_bookings(FINANCE_CONTROLLER,
                          {"client_id": scenario["other"]["id"], "limit": 10,
                           "offset": 0}),
        expected_total=1, expected_rows=1,
    )
    assert by_client[0]["id"] == scenario["fourth"]["id"]
    assert by_client[0]["client_id"] == scenario["other"]["id"]

    by_status = assert_list_page(
        api.list_bookings(FINANCE_CONTROLLER,
                          {"fulfillment_status": "CANCELLED", "limit": 10,
                           "offset": 0}),
        expected_total=1, expected_rows=1,
    )
    assert by_status[0]["id"] == scenario["third"]["id"]
    assert by_status[0]["fulfillment_status"] == "CANCELLED"


def test_a_page_size_of_a_hundred_is_accepted_and_a_hundred_and_one_is_not(
    api: ApiClient,
) -> None:
    """The page-size bound is inclusive at its maximum and malformed above it.

    Asking for exactly the maximum is a legitimate request and answers with the
    whole set; asking for one more is not a business conflict but a malformed
    request, so it is refused before any of the domain rules are consulted.

    PRD §2.3: "`limit` caps the number of records returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "A `limit` outside that inclusive range is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/list_endpoints_page_and_filter_on_their_declared_keys_only
    """
    scenario = _four_bookings_across_two_buyers(api)

    at_bound = assert_list_page(
        api.list_bookings(FINANCE_CONTROLLER, {"limit": 100, "offset": 0}),
        expected_total=4, expected_rows=4, expected_limit=100,
        expected_has_more=False,
    )
    assert at_bound[0]["id"] == scenario["first"]["id"]

    validate_error(
        api.list_bookings(FINANCE_CONTROLLER, {"limit": 101, "offset": 0}),
        ERR_INVALID_REQUEST,
    )


# --------------------------------------------------------------------------
# Settlement: an empty-bodied action that waits for the fixture
# --------------------------------------------------------------------------


def _fully_released_deal_with_an_exhausted_block(api: ApiClient) -> Dict[str, Any]:
    """Twenty contracted units, all released, all allocated to one channel.

    The deal guarantees nothing, so its liability is purely the twenty released
    units at eighty cents each. The CORPORATE block is filled to its target of
    twenty by the confirmation and nothing is sold from it.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=20,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=20,
                       priority_rank=1)
    release_deal(api, deal["id"], 20)
    return {"event": event, "deal": deal, "block": read_block(api, block["id"])}


def test_settlement_is_refused_until_the_fixture_is_finished_then_accepted_verbatim(
    api: ApiClient,
) -> None:
    """The same empty-bodied call is a conflict, then a success.

    The deal's own status was never the problem — it is already
    `FULLY_RELEASED` with no promise still pending — so the first refusal is the
    fixture half of the precondition. Nothing about the request changes; the
    fixture is played and the identical call then settles the deal, stamping the
    logical clock and freezing the liability at the twenty released units times
    eighty cents.

    PRD §3.1: "Settlement is permitted only when `deal_status` is `PARTIALLY_RELEASED`, `FULLY_RELEASED` or `SHORTFALL_DECLARED`, the fixture has reached `COMPLETED` or `CANCELLED`, and no tranche of the deal is still `PENDING`; any of those failing gives `ERR_INVALID_DEAL_STATE`."
    PRD §3.1: "Third, the shortfall unit cost is obtained by taking sixty percent of `unit_cost_cents` and rounding that single per-unit figure half-up to a whole cent, and `minimum_liability_cents` is then `released_units` multiplied by `unit_cost_cents`, plus `shortfall_units` multiplied by that already-rounded shortfall unit cost."
    PRD §2.4: "Wherever a field below is described as being stamped with the current instant — `confirmed_at`, `lapsed_at`, `recalled_at`, `settled_at`, `priced_at`, `published_at`, `paid_at`, `released_at`, `run_at` — the value written is the logical clock's value at the moment of the write."

    Design: Corner/endpoints/settle_is_an_action_endpoint_that_waits_for_the_fixture_to_finish
    """
    scenario = _fully_released_deal_with_an_exhausted_block(api)
    deal_id = scenario["deal"]["id"]
    before = get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))
    assert before["deal_status"] == "FULLY_RELEASED"
    assert before["settled_at"] is None

    validate_error(api.settle_rights_deal(deal_id, FINANCE_CONTROLLER),
                   ERR_INVALID_DEAL_STATE)

    set_clock(api, "2027-02-02T00:00:00Z")
    completed = get_success_data(
        api.complete_event(scenario["event"]["id"], RIGHTS_MANAGER)
    )
    assert completed["status"] == "COMPLETED"

    settled = get_success_data(api.settle_rights_deal(deal_id, FINANCE_CONTROLLER))
    assert settled["deal_status"] == "SETTLED"
    assert settled["settled_at"] == "2027-02-02T00:00:00.000Z"
    assert settled["minimum_liability_cents"] == 160000


def test_settlement_recalls_the_sibling_block_and_cannot_be_replayed(
    api: ApiClient,
) -> None:
    """The side effect lands on another entity, and the action is not idempotent.

    Settling the deal reaches the block that was never named in the call: it is
    recalled with a stamp at the logical clock, and its twenty allocated units are
    frozen at that figure rather than zeroed, because recall preserves what the
    channel held. `SETTLED` is terminal, so repeating the call is a state
    conflict.

    PRD §3.1: "Settlement moves `deal_status` to `SETTLED`, stamps `settled_at`, freezes `minimum_liability_cents` at its final recomputed value, moves every one of the deal's blocks whose `block_state` is `OPEN` or `EXHAUSTED` to `RECALLED` with `recalled_at` stamped, and recomputes the fixture's `fulfillment_risk_score` and `risk_posture`."
    PRD §3.1: "`SETTLED` and `TERMINATED` are the two terminal deal states; the latter is reached only when the fixture itself is cancelled."

    Design: Corner/endpoints/settle_is_an_action_endpoint_that_waits_for_the_fixture_to_finish
    """
    scenario = _fully_released_deal_with_an_exhausted_block(api)
    deal_id = scenario["deal"]["id"]
    assert scenario["block"]["block_state"] == "EXHAUSTED"
    assert scenario["block"]["allocated_units"] == 20

    set_clock(api, "2027-02-02T00:00:00Z")
    get_success_data(api.complete_event(scenario["event"]["id"], RIGHTS_MANAGER))
    get_success_data(api.settle_rights_deal(deal_id, FINANCE_CONTROLLER))

    block = read_block(api, scenario["block"]["id"])
    assert block["block_state"] == "RECALLED"
    assert block["recalled_at"] == "2027-02-02T00:00:00.000Z"
    assert block["allocated_units"] == 20

    validate_error(api.settle_rights_deal(deal_id, FINANCE_CONTROLLER),
                   ERR_INVALID_DEAL_STATE)


# --------------------------------------------------------------------------
# The rollover sweep: one call across every fixture
# --------------------------------------------------------------------------


def _two_fixtures_with_stale_promises_and_stale_money(api: ApiClient) -> Dict[str, Any]:
    """Two unrelated fixtures, each with a promise and an installment gone stale.

    Each fixture carries a forty-unit deal guaranteeing twenty with a single
    thirty-unit promise due 2026-09-01, a published BRONZE package and one
    five-unit CORPORATE sale to its own buyer. Because neither deal has released
    anything, each sale carries the guarantee surcharge and nets 587520, whose
    first schedule line falls due 2026-08-04. The clock is then moved to
    2026-09-02, which is past both dates.
    """
    reset_clock(api)
    first_event = make_event(api)
    second_event = make_event(api, name="Northern Derby", venue_name="Harbour Park",
                              hospitality_zone_codes=["ZONE_C"],
                              event_date="2027-03-01T15:00:00.000Z")

    fixtures = []
    for index, event in enumerate((first_event, second_event)):
        deal = make_committed_deal(api, event["id"], contracted_units=40,
                                   guaranteed_minimum_units=20, unit_cost_cents=8000)
        tranche = make_tranche(api, deal["id"], promised_units=30,
                               promised_release_at="2026-09-01T00:00:00.000Z")
        package = make_published_bronze_package(api, event["id"])
        client = make_client(api, name=f"Buyer {index}")
        booking = make_booking(api, client["id"], package["id"],
                               channel="CORPORATE", units=5)
        fixtures.append({"event": event, "deal": deal, "tranche": tranche,
                         "package": package, "client": client, "booking": booking})

    set_clock(api, "2026-09-02T00:00:00Z")
    return {"first": fixtures[0], "second": fixtures[1]}


def test_one_rollover_call_lapses_ages_and_re_bands_across_both_fixtures(
    api: ApiClient,
) -> None:
    """A single empty-bodied sweep touches two fixtures and reports four counts.

    Both promises are past their release date, so both lapse and both deals fall
    into shortfall: with nothing released and nothing still promised, the
    guarantee of twenty is owed at the rounded sixty-percent unit cost, which is
    96000. Both first installments are past due, so both age and both buyers drop
    to `ON_HOLD` on one overdue line each. Every counter is the number of
    transitions this run performed.

    PRD §3.6: "First it lapses promises: every `PENDING` tranche whose `promised_release_at` is now behind the logical clock moves to `LAPSED` as described in §3.2, in ascending `promised_release_at` order with `created_at` ascending as the tie-break, bumping each affected deal's `version` and re-running the minimum-liability calculation and the deal status function."
    PRD §3.6: "Second it ages money: every `SCHEDULED` installment whose `due_at` is now behind the logical clock moves `SCHEDULED → OVERDUE` and has its `days_overdue` recomputed as the whole days between its `due_at` and the logical clock; an installment that is not `OVERDUE` reports `days_overdue` as 0."
    PRD §3.6: "A client with an `overdue_installment_count` of at least 1 and at most 2 lands on `ON_HOLD` — whether it arrives there from `ACTIVE` or back up from `BLOCKED`."
    PRD §3.2: "The first hop sets `deal_status` to `SHORTFALL_DECLARED` and `shortfall_units` to `guaranteed_minimum_units` minus `released_units`."

    Design: Corner/endpoints/the_daily_run_sweeps_every_event_in_one_call_and_reports_transition_counts
    """
    scenario = _two_fixtures_with_stale_promises_and_stale_money(api)

    report = daily_run(api)

    assert_daily_run_report(report, run_at="2026-09-02T00:00:00.000Z", lapsed=2,
                            overdue=2, shortfall=2, client_changes=2)

    for side in ("first", "second"):
        tranche = get_success_data(
            api.get_release_tranche(scenario[side]["tranche"]["id"], RIGHTS_MANAGER)
        )
        assert tranche["tranche_state"] == "LAPSED"
        assert tranche["lapsed_at"] == "2026-09-02T00:00:00.000Z"

    deal = get_success_data(
        api.get_rights_deal(scenario["first"]["deal"]["id"], FINANCE_CONTROLLER)
    )
    assert deal["deal_status"] == "SHORTFALL_DECLARED"
    assert deal["shortfall_units"] == 20
    assert deal["minimum_liability_cents"] == 96000

    buyer = get_success_data(
        api.get_client(scenario["second"]["client"]["id"], FINANCE_CONTROLLER)
    )
    assert buyer["client_status"] == "ON_HOLD"
    assert buyer["overdue_installment_count"] == 1


def test_an_immediately_repeated_rollover_reports_zeros_and_restamps_nothing(
    api: ApiClient,
) -> None:
    """The counters are per-run transitions, not standing totals.

    Nothing is left to lapse or age, so the second sweep reports four zeros while
    still answering with the clock it ran at. The rows the first sweep moved are
    untouched: the tranche is still `LAPSED` and keeps the lapse stamp it was
    given, rather than being restamped at the second run's instant.

    PRD §3.6: "The sweep answers with `run_at`, the logical instant it ran; `lapsed_tranche_count`, how many tranches it lapsed; `overdue_installment_count`, how many installments it aged into `OVERDUE`; `shortfall_deal_count`, how many deals it pushed into `SHORTFALL_DECLARED`; and `client_status_change_count`, how many clients changed credit standing."
    PRD §3.2: "`CONFIRMED`, `SHORT_CONFIRMED` and `LAPSED` are all terminal tranche states."

    Design: Corner/endpoints/the_daily_run_sweeps_every_event_in_one_call_and_reports_transition_counts
    """
    scenario = _two_fixtures_with_stale_promises_and_stale_money(api)
    daily_run(api)

    again = daily_run(api)

    assert_daily_run_report(again, run_at="2026-09-02T00:00:00.000Z", lapsed=0,
                            overdue=0, shortfall=0, client_changes=0)

    tranche = get_success_data(
        api.get_release_tranche(scenario["first"]["tranche"]["id"], RIGHTS_MANAGER)
    )
    assert tranche["tranche_state"] == "LAPSED"
    assert tranche["lapsed_at"] == "2026-09-02T00:00:00.000Z"


# --------------------------------------------------------------------------
# The margin report changes nothing
# --------------------------------------------------------------------------


def _guaranteed_deal_awaiting_release(api: ApiClient) -> Dict[str, Any]:
    """A fixture carrying nothing but a guarantee it has not yet been paid for.

    Twenty contracted units guarantee all twenty, and nothing has been released,
    so the whole guarantee sits in the liability at the rounded sixty-percent unit
    cost: 96000. There are no builds, packages or sales.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=20,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)
    return {"event": event, "deal": deal}


def test_the_margin_report_reads_identically_twice_and_moves_nothing_on_the_fixture(
    api: ApiClient,
) -> None:
    """A read repeated under a second authorised role returns the same object.

    With no sales there is no revenue, so the whole guarantee shows up as a
    negative margin and the percentage stays at the declared zero rather than
    dividing by it. Nothing has been released, so there is no unsold exposure to
    carry. Reading the report twice leaves the fixture's own version and risk
    score exactly where they were, and the report is not an entity: it carries no
    identifier, no version and no creation stamp.

    PRD §3.9: "While the fixture's `status` is `SCHEDULED`, `POSTPONED` or `RESCHEDULED` the report defaults to `PROVISIONAL`; once the fixture's `status` is `COMPLETED` or `CANCELLED` it defaults to `FINAL`."
    PRD §3.9: "And `margin_pct` is `net_margin_cents` divided by `revenue_cents`, rounded half-up to four decimal places, except that where `revenue_cents` is 0 the reported margin percentage is 0."
    PRD §3.9: "The report answers with `variant`, `revenue_cents`, `rights_cost_cents`, `build_cost_cents`, `cost_cents`, `unsold_units`, `unsold_exposure_cents`, `margin_cents`, `net_margin_cents` and `margin_pct`."

    Design: Corner/endpoints/the_margin_report_is_a_pure_computed_read
    """
    scenario = _guaranteed_deal_awaiting_release(api)
    event_id = scenario["event"]["id"]
    before = read_event(api, event_id)

    first = get_success_data(api.get_margin_report(event_id, FINANCE_CONTROLLER))
    assert_margin_report(first, variant="PROVISIONAL", revenue=0, rights_cost=96000,
                         build_cost=0, cost=96000, unsold_units=0,
                         unsold_exposure=0, margin=-96000, net_margin=-96000,
                         margin_pct=0.0000)
    for absent in ("id", "version", "created_at"):
        assert absent not in first

    second = get_success_data(api.get_margin_report(event_id, COMMERCIAL_DIRECTOR))
    assert second == first

    after = read_event(api, event_id)
    assert after["version"] == before["version"]
    assert after["fulfillment_risk_score"] == before["fulfillment_risk_score"] == 0


def test_only_an_approved_build_moves_the_margin_report_cost_base(
    api: ApiClient,
) -> None:
    """The report follows a real mutation and nothing else.

    Planning a build-out on its own would leave the cost base alone; signing it
    off pulls all 220000 of it in, so the cost becomes the guarantee plus the
    build-out and the net margin falls to exactly that figure. The percentage is
    still the declared zero, because there is still no revenue to divide by.

    PRD §3.9: "`build_cost_cents` is the total of `total_cost_cents` across the fixture's hospitality builds whose `build_state` is `APPROVED`, `READY` or `CLOSED`; builds that are still `PLANNED` and builds that were `CANCELLED` never enter the cost base."
    PRD §3.9: "`margin_cents` is `revenue_cents` less `cost_cents`."
    PRD §3.9: "`net_margin_cents` is `margin_cents` less `unsold_exposure_cents`."

    Design: Corner/endpoints/the_margin_report_is_a_pure_computed_read
    """
    scenario = _guaranteed_deal_awaiting_release(api)
    event_id = scenario["event"]["id"]
    build = make_build(api, event_id, zone_code="ZONE_A", space_units=30,
                       catering_covers=20, staff_count=5)
    approved = approve_build(api, build["id"])
    assert approved["build_state"] == "APPROVED"
    assert approved["total_cost_cents"] == 220000

    report = get_success_data(
        api.get_margin_report(event_id, FINANCE_CONTROLLER, {"variant": "PROVISIONAL"})
    )

    assert_margin_report(report, variant="PROVISIONAL", revenue=0,
                         rights_cost=96000, build_cost=220000, cost=316000,
                         unsold_units=0, unsold_exposure=0, margin=-316000,
                         net_margin=-316000, margin_pct=0.0000)


# --------------------------------------------------------------------------
# Filtered lists as the only reverse path
# --------------------------------------------------------------------------


def _two_buyers_on_a_two_line_package(api: ApiClient) -> Dict[str, Any]:
    """Two sales of a two-line BRONZE package, one of them allocated.

    The package adds a hotel night to the ticket pair, so it lists at 150000 and
    a five-unit CORPORATE sale nets 698400 on an unexposed fixture. Only the first
    sale draws from the block, which is what lets the block filter be told apart
    from the package filter.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    tranche = release_deal(api, deal["id"], 40)

    package = make_bronze_package(api, event["id"])
    ticket_line = add_component(api, package["id"])
    hotel_line = add_component(api, package["id"], component_type="HOTEL",
                               descriptor="One night, city centre", quantity=1,
                               unit_cost_cents=20000, markup_pct=0.5000,
                               sequence_no=2)
    priced = price_package(api, package["id"])
    published = publish_package(api, package["id"], priced["version"])

    buyer = make_client(api, name="Northbridge Capital", client_type="CORPORATE")
    other = make_client(api, name="Vantage Partners", client_type="TRAVEL_PARTNER")
    allocated = make_booking(api, buyer["id"], package["id"], channel="CORPORATE",
                             units=5)
    unallocated = make_booking(api, other["id"], package["id"], channel="CORPORATE",
                               units=5)
    allocate_booking(api, allocated["id"], block["id"])

    return {"event": event, "deal": deal, "block": read_block(api, block["id"]),
            "tranche": tranche, "package": published, "ticket_line": ticket_line,
            "hotel_line": hotel_line, "buyer": buyer, "other": other,
            "allocated": allocated, "unallocated": unallocated}


def test_a_package_is_walked_back_to_from_its_component_lines(
    api: ApiClient,
) -> None:
    """The component collection filtered by package is the only path down to it.

    Both lines come back for this package and only for this package, in ordinal
    order, and the pricing they drove is the ticket pair's 120000 plus the hotel
    night's 30000. There is no nested path under the package to fall back on.

    PRD §2.8: "Every collection in this API sits at the root of the URL space, and no relationship is expressed by nesting one resource inside another's path."
    PRD §3.4: "Component lines are added by a `CommercialManager` only."

    Design: Corner/endpoints/filtered_list_gets_are_the_only_reverse_path_from_a_child_to_its_parent
    """
    scenario = _two_buyers_on_a_two_line_package(api)
    assert_package_pricing(scenario["package"], base_cost=120000, subtotal=150000,
                           list_price=150000, margin_pct=0.2000, status="PUBLISHED")

    rows = assert_list_page(
        api.list_package_components(
            COMMERCIAL_MANAGER,
            {"package_product_id": scenario["package"]["id"], "limit": 10,
             "offset": 0},
        ),
        expected_total=2, expected_rows=2,
    )

    assert ids_of(rows) == [scenario["ticket_line"]["id"],
                            scenario["hotel_line"]["id"]]
    assert [row["sequence_no"] for row in rows] == [1, 2]
    assert [row["line_price_cents"] for row in rows] == [120000, 30000]


def test_a_block_and_a_package_are_walked_back_to_from_their_bookings(
    api: ApiClient,
) -> None:
    """The block filter finds one sale where the package filter finds both.

    The two sales sit on the same package, so filtering by package returns both in
    creation order. Only one of them draws from the block, and the server wrote
    that link itself rather than accepting it on the sale, so filtering by block
    returns exactly that one.

    PRD §2.8: "Some foreign keys are never client-supplied: a booking's `allocation_block_id` is written by the server when inventory is committed to that booking and cleared back to null when the booking is reverted, rebooked or cancelled, and an installment's `booking_id` and `sequence_no` are written by the server because installments are only ever created as a consequence of booking creation, rebooking or cancellation settlement — never by a direct client call."
    PRD §2.3: "Every filter is optional and filters combine conjunctively."

    Design: Corner/endpoints/filtered_list_gets_are_the_only_reverse_path_from_a_child_to_its_parent
    """
    scenario = _two_buyers_on_a_two_line_package(api)

    by_block = assert_list_page(
        api.list_bookings(CLIENT_SERVICE_AGENT,
                          {"allocation_block_id": scenario["block"]["id"],
                           "limit": 10, "offset": 0}),
        expected_total=1, expected_rows=1,
    )
    assert by_block[0]["id"] == scenario["allocated"]["id"]
    assert by_block[0]["allocation_block_id"] == scenario["block"]["id"]
    assert by_block[0]["net_price_cents"] == 698400

    by_package = assert_list_page(
        api.list_bookings(CLIENT_SERVICE_AGENT,
                          {"package_product_id": scenario["package"]["id"],
                           "limit": 10, "offset": 0}),
        expected_total=2, expected_rows=2,
    )
    assert ids_of(by_package) == [scenario["allocated"]["id"],
                                  scenario["unallocated"]["id"]]
    assert read_booking(api, scenario["unallocated"]["id"])["allocation_block_id"] is None


def test_a_schedule_a_promise_and_a_block_are_only_reachable_through_their_filters(
    api: ApiClient,
) -> None:
    """Six installments exist; the booking filter returns that booking's three.

    The schedule was never returned by the call that created it, so this list is
    the only way to discover it at all, and it comes back with its own parent
    stamped on every row and its sequence numbers running 1 to 3. The same
    backwards walk reaches the deal's promise and the deal's block, neither of
    which has a nested path either.

    PRD §3.6: "Installment rows are discoverable only through the installment list filtered by `booking_id`; each row carries its parent `booking_id`, a 1-based `sequence_no` unique within that booking, an `amount_cents`, a `due_at`, an `installment_kind` and an `installment_state`, plus `paid_amount_cents` at 0, `paid_at` unset and `days_overdue` at 0."
    PRD §2.8: "A release tranche is created by posting to the tranche collection with a `rights_deal_id` in the body, not by posting under a deal; an allocation block carries `rights_deal_id`; a package carries `event_id`; a component carries `package_product_id`; a booking carries `client_id` and `package_product_id`; a build carries `event_id`; a host assignment carries `on_site_host_id`, `booking_id` and `hospitality_build_id`."

    Design: Corner/endpoints/filtered_list_gets_are_the_only_reverse_path_from_a_child_to_its_parent
    """
    scenario = _two_buyers_on_a_two_line_package(api)
    assert_total_count(
        api.list_payment_installments(FINANCE_CONTROLLER, {"limit": 100}), 6
    )

    schedule = assert_list_page(
        api.list_payment_installments(
            FINANCE_CONTROLLER,
            {"booking_id": scenario["unallocated"]["id"], "limit": 10, "offset": 0},
        ),
        expected_total=3, expected_rows=3,
    )
    assert all(row["booking_id"] == scenario["unallocated"]["id"]
               for row in schedule)
    assert [row["sequence_no"] for row in schedule] == [1, 2, 3]
    assert [row["amount_cents"] for row in schedule] == [209520, 279360, 209520]

    promises = assert_list_page(
        api.list_release_tranches(RIGHTS_MANAGER,
                                  {"rights_deal_id": scenario["deal"]["id"],
                                   "limit": 10, "offset": 0}),
        expected_total=1, expected_rows=1,
    )
    assert promises[0]["id"] == scenario["tranche"]["id"]
    assert promises[0]["rights_deal_id"] == scenario["deal"]["id"]

    blocks = assert_list_page(
        api.list_allocation_blocks(RIGHTS_MANAGER,
                                   {"rights_deal_id": scenario["deal"]["id"],
                                    "limit": 10, "offset": 0}),
        expected_total=1, expected_rows=1,
    )
    assert blocks[0]["id"] == scenario["block"]["id"]
    assert blocks[0]["rights_deal_id"] == scenario["deal"]["id"]


# --------------------------------------------------------------------------
# One postponement path, two behaviours
# --------------------------------------------------------------------------


def _reserved_sale_on_a_scheduled_fixture(api: ApiClient) -> Dict[str, Any]:
    """One five-unit CORPORATE sale, still unallocated, on a live fixture.

    The sale nets 558720 on an unexposed fixture and carries the three-line
    schedule, which is what makes the difference between a freezing postponement
    and a re-dating one observable on the schedule as well as on the fixture.
    """
    scenario = _published_bronze_fixture(api)
    client = make_client(api)
    booking = make_booking(api, client["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    scenario["client"] = client
    scenario["booking"] = booking
    return scenario


def test_the_first_postponement_freezes_the_book_and_opens_a_rebooking_window(
    api: ApiClient,
) -> None:
    """Called with no replacement date, the path freezes everything it reaches.

    The kick-off is left exactly where it was because no replacement was named,
    but the original kick-off is now preserved on the fixture, the count of
    postponements has moved to one, and a three-week rebooking window opens from
    the logical clock of 2026-08-01. The reserved sale is frozen into
    REBOOK_PENDING and all three of its schedule lines are pulled onto the new
    deadline.

    PRD §3.8: "The fixture stamps `original_event_date` with its current `event_date` — but only when `original_event_date` is still unset, so the first-ever scheduled kick-off is preserved and never overwritten by a later postponement."
    PRD §3.8: "`postponement_count` increases by one, `status` becomes `POSTPONED`, and `rebook_deadline_at` is set to twenty-one days after the logical clock — the rebooking window is three weeks wide and is re-opened from scratch on every fresh postponement."
    PRD §3.8: "Every booking on a package of this fixture whose `fulfillment_status` is `RESERVED`, `ALLOCATED` or `CREDENTIALED` moves to `REBOOK_PENDING`, processed in ascending `created_at` order."

    Design: Corner/endpoints/postpone_means_freeze_the_first_time_and_only_re_date_the_second
    """
    scenario = _reserved_sale_on_a_scheduled_fixture(api)
    assert scenario["booking"]["fulfillment_status"] == "RESERVED"
    assert scenario["booking"]["net_price_cents"] == 558720

    postponed = get_success_data(
        api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER)
    )

    assert postponed["status"] == "POSTPONED"
    assert postponed["postponement_count"] == 1
    assert postponed["rebook_deadline_at"] == "2026-08-22T00:00:00.000Z"
    assert postponed["event_date"] == "2027-02-01T15:00:00.000Z"
    assert postponed["original_event_date"] == "2027-02-01T15:00:00.000Z"

    assert read_booking(api, scenario["booking"]["id"])["fulfillment_status"] == \
        "REBOOK_PENDING"
    lines = installments_of(api, scenario["booking"]["id"])
    assert [line["due_at"] for line in lines] == ["2026-08-22T00:00:00.000Z"] * 3


def test_the_second_postponement_only_re_dates_and_leaves_the_frozen_book_alone(
    api: ApiClient,
) -> None:
    """Called again with a replacement date, the same path is much narrower.

    From POSTPONED the call confirms a replacement kick-off and nothing else: the
    fixture reaches RESCHEDULED with the new date, the postponement count does not
    move a second time, and the rebooking deadline stays on 2026-08-22 rather than
    being re-opened from the new clock of 2026-08-05. The first-ever kick-off is
    still preserved, the frozen sale is not rebooked by naming a date, and its
    schedule lines are not re-dated again.

    PRD §3.8: "The fixture moves `POSTPONED → RESCHEDULED`, `event_date` becomes the supplied replacement, and `rebook_deadline_at` is left exactly as it was."
    PRD §3.8: "Bookings already sitting in `REBOOK_PENDING` stay in `REBOOK_PENDING`: naming a replacement date does not rebook anybody."

    Design: Corner/endpoints/postpone_means_freeze_the_first_time_and_only_re_date_the_second
    """
    scenario = _reserved_sale_on_a_scheduled_fixture(api)
    get_success_data(api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER))
    set_clock(api, "2026-08-05T00:00:00Z")

    rescheduled = get_success_data(
        api.postpone_event(scenario["event"]["id"],
                           {"new_event_date": "2027-03-15T15:00:00.000Z"},
                           RIGHTS_MANAGER)
    )

    assert rescheduled["status"] == "RESCHEDULED"
    assert rescheduled["event_date"] == "2027-03-15T15:00:00.000Z"
    assert rescheduled["postponement_count"] == 1
    assert rescheduled["rebook_deadline_at"] == "2026-08-22T00:00:00.000Z"
    assert rescheduled["original_event_date"] == "2027-02-01T15:00:00.000Z"

    assert read_booking(api, scenario["booking"]["id"])["fulfillment_status"] == \
        "REBOOK_PENDING"
    lines = installments_of(api, scenario["booking"]["id"])
    assert [line["due_at"] for line in lines] == ["2026-08-22T00:00:00.000Z"] * 3
