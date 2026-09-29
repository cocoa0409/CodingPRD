"""Layers that cut across the whole request: version pinning, rate thresholds
and the rollover checkpoint.

Three of the probes below drive optimistic concurrency on a different parent
each time — the allocation block, the rights deal and the package product — and
each one shows the refusal leaving both sides untouched before replaying the
identical intent against a freshly read version. The remaining two pin a money
ladder that runs downward as the amount grows, and the rule that a logical clock
on its own moves nothing until the operations run is invoked.
"""

from typing import Any, Dict

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_DIRECTOR_AS_PRICER,
    FINANCE_CONTROLLER,
    RIGHTS_MANAGER,
    ApiClient,
    add_component,
    allocate_payload,
    assert_booking_price_buildup,
    assert_daily_run_report,
    assert_deal_position,
    assert_exactly_one_succeeds,
    assert_fraction_4dp,
    assert_package_pricing,
    assert_schedule_amounts,
    assert_version_incremented,
    confirm_tranche_payload,
    daily_run,
    deal_version,
    get_success_data,
    installments_of,
    make_block,
    make_booking,
    make_bronze_package,
    make_client,
    make_committed_deal,
    make_event,
    make_tranche,
    price_package,
    publish_package,
    publish_payload,
    read_block,
    read_booking,
    read_client,
    release_deal,
    reset_clock,
    run_race,
    set_clock,
    validate_error,
)

# The round-numbered BRONZE line: two seats at 50000 cents marked up 20 percent.
_BRONZE_LINE = {
    "component_type": "TICKET",
    "descriptor": "Category 1 seat pair",
    "quantity": 2,
    "unit_cost_cents": 50000,
    "markup_pct": 0.2000,
    "sequence_no": 1,
}


def _read_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))


def _read_tranche(api: ApiClient, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_release_tranche(tranche_id, RIGHTS_MANAGER))


def _read_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_package_product(package_id, COMMERCIAL_DIRECTOR))


def _publish_bronze(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    """One BRONZE package taken DRAFT -> PRICED -> PUBLISHED on a fixture."""
    package = make_bronze_package(api, event_id, **overrides)
    add_component(api, package["id"], **_BRONZE_LINE)
    priced = price_package(api, package["id"])
    return publish_package(api, priced["id"], priced["version"])


# --------------------------------------------------------------------------
# Two bookings, one block
# --------------------------------------------------------------------------


def _two_bookings_on_one_block(api: ApiClient) -> Dict[str, Any]:
    """A block with 40 released units and two five-unit bookings wanting in.

    Both bookings are legal against the block — it has room for either of them
    and for both — so nothing but the version can separate the two writers.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    release_deal(api, deal["id"], 40)
    package = _publish_bronze(api, event["id"])
    first_client = make_client(api, name="Northbridge Capital")
    second_client = make_client(api, name="Vantage Partners")
    first = make_booking(api, first_client["id"], package["id"],
                         channel="CORPORATE", units=5)
    second = make_booking(api, second_client["id"], package["id"],
                          channel="CORPORATE", units=5)
    return {
        "event": event,
        "deal": deal,
        "block": read_block(api, block["id"]),
        "package": package,
        "first": first,
        "second": second,
    }


def test_the_loser_of_a_block_allocation_must_re_read_before_it_can_commit(
    api: ApiClient,
) -> None:
    """The stale writer is refused outright, then replays the same intent.

    The winning allocation moves the booking to ALLOCATED, stamps its block, and
    advances the block by one version while committing five units times the two
    tickets each package carries. The second booking, still holding the version it
    read before that, is refused with a stale-block-version failure even though
    thirty of the forty units are still free — nothing about its own request was
    invalid. The refusal is total: the booking is still RESERVED with no block,
    and the block's version and committed count are exactly where the winner left
    them. Replayed against the freshly read version the identical request
    succeeds and the block advances once more.

    PRD §2.6: "If the block's `version` has advanced since the client last read it
    — because another agent allocated a different booking against the same block,
    or because a waterfall pass or a recall touched it — the request is rejected
    with `ERR_STALE_BLOCK_VERSION` (HTTP 412)."

    PRD §3.5: "On success the booking moves `RESERVED → ALLOCATED`, its
    `allocation_block_id` is set, the block's `committed_units` increases by the
    booking's `units` multiplied by `tickets_per_package`, the block's `version`
    increases by one, and the fixture's `fulfillment_risk_score` and
    `risk_posture` are recomputed."

    Design: Corner/cross_cutting_complexity_layers/two_bookings_race_for_the_same_block_and_the_loser_must_re_read
    """
    scenario = _two_bookings_on_one_block(api)
    block_id = scenario["block"]["id"]
    before = read_block(api, block_id)
    assert before["committed_units"] == 0

    winner = get_success_data(
        api.allocate_booking(scenario["first"]["id"],
                             allocate_payload(block_id, before["version"]),
                             CLIENT_SERVICE_AGENT)
    )
    assert winner["fulfillment_status"] == "ALLOCATED"
    assert winner["allocation_block_id"] == block_id

    after_win = read_block(api, block_id)
    assert_version_incremented(after_win["version"], before["version"])
    assert after_win["committed_units"] == 10, (
        "five units of a two-ticket package commit ten ticket units"
    )
    assert after_win["allocated_units"] - after_win["committed_units"] == 30, (
        "thirty of the forty allocated units are still free, so the loser is "
        "not short of inventory"
    )

    refused = api.allocate_booking(scenario["second"]["id"],
                                   allocate_payload(block_id, before["version"]),
                                   CLIENT_SERVICE_AGENT)
    validate_error(refused, "ERR_STALE_BLOCK_VERSION", 412)

    untouched = read_booking(api, scenario["second"]["id"])
    assert untouched["fulfillment_status"] == "RESERVED"
    assert untouched["allocation_block_id"] is None
    unmoved = read_block(api, block_id)
    assert unmoved["version"] == after_win["version"]
    assert unmoved["committed_units"] == 10

    replayed = get_success_data(
        api.allocate_booking(scenario["second"]["id"],
                             allocate_payload(block_id, unmoved["version"]),
                             CLIENT_SERVICE_AGENT)
    )
    assert replayed["fulfillment_status"] == "ALLOCATED"
    assert replayed["allocation_block_id"] == block_id
    settled = read_block(api, block_id)
    assert_version_incremented(settled["version"], unmoved["version"])
    assert settled["committed_units"] == 20


def test_two_bookings_racing_on_one_block_version_leave_exactly_one_winner(
    api: ApiClient,
) -> None:
    """Both writers pin the same version concurrently; the block moves once.

    Neither request is distinguishable on state — the block has room for both —
    so whichever arrives second must be the one carrying a version the first has
    already superseded. Exactly one succeeds, the other is a stale-block-version
    refusal, and the block ends up one version further on with the ten ticket
    units of a single five-unit booking committed.

    PRD §2.6: "Allocating a booking against a channel block requires
    `expected_allocation_block_version` in the request body."

    PRD §2.6: "Its value must equal the target `AllocationBlock`'s current
    `version`."

    PRD §2.7: "Checks are evaluated in the fixed sequence below and the first
    failing check produces the response."

    Design: Corner/cross_cutting_complexity_layers/two_bookings_race_for_the_same_block_and_the_loser_must_re_read
    """
    scenario = _two_bookings_on_one_block(api)
    block_id = scenario["block"]["id"]
    pinned = read_block(api, block_id)["version"]

    outcome = assert_exactly_one_succeeds(*run_race(
        lambda: api.allocate_booking(scenario["first"]["id"],
                                     allocate_payload(block_id, pinned),
                                     CLIENT_SERVICE_AGENT),
        lambda: api.allocate_booking(scenario["second"]["id"],
                                     allocate_payload(block_id, pinned),
                                     CLIENT_SERVICE_AGENT),
    ))
    validate_error(outcome["failures"][0], "ERR_STALE_BLOCK_VERSION", 412)

    final = read_block(api, block_id)
    assert_version_incremented(final["version"], pinned)
    assert final["committed_units"] == 10, (
        "only the winning allocation committed inventory"
    )


# --------------------------------------------------------------------------
# Two sibling tranches, one parent deal
# --------------------------------------------------------------------------


def _two_pending_tranches(api: ApiClient) -> Dict[str, Any]:
    """A committed deal carrying two PENDING twenty-unit promises."""
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)
    first = make_tranche(api, deal["id"], promised_units=20,
                         promised_release_at="2026-10-01T00:00:00.000Z")
    second = make_tranche(api, deal["id"], promised_units=20,
                          promised_release_at="2026-11-01T00:00:00.000Z")
    return {"event": event, "deal": deal, "first": first, "second": second}


def test_the_sibling_tranche_needs_the_version_the_first_confirmation_produced(
    api: ApiClient,
) -> None:
    """The pinned token belongs to the parent deal, not to the tranche in the path.

    Both tranches are PENDING, so state separates neither of them; the first
    confirmation succeeds and moves the parent deal's version and released
    quantity. The second, still holding the deal version from before that, is
    refused with a stale-deal-version failure and leaves the tranche PENDING with
    nothing confirmed and the deal's released quantity frozen at twenty. Carrying
    the version the first write produced, the same request then completes the
    contract.

    PRD §2.6: "Confirming a release tranche requires `expected_rights_deal_version`
    in the request body, a required field whose value must equal the current
    `version` of the tranche's parent `RightsDeal`."

    PRD §2.6: "A mismatch is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412)."

    PRD §3.2: "A new tranche opens in `PENDING` with `confirmed_units` at 0 and
    `confirmed_at` and `lapsed_at` unset."

    Design: Corner/cross_cutting_complexity_layers/a_second_tranche_confirmation_needs_the_version_the_first_one_produced
    """
    scenario = _two_pending_tranches(api)
    deal_id = scenario["deal"]["id"]
    opening = _read_deal(api, deal_id)
    assert opening["released_units"] == 0
    pinned = opening["version"]

    first = get_success_data(
        api.confirm_release_tranche(scenario["first"]["id"],
                                    confirm_tranche_payload(pinned, 20),
                                    RIGHTS_MANAGER)
    )
    assert first["tranche_state"] == "CONFIRMED"
    assert first["confirmed_units"] == 20

    moved = _read_deal(api, deal_id)
    assert_version_incremented(moved["version"], pinned)
    assert_deal_position(moved, released=20, shortfall=0, liability=160000,
                         status="PARTIALLY_RELEASED")

    refused = api.confirm_release_tranche(scenario["second"]["id"],
                                          confirm_tranche_payload(pinned, 20),
                                          RIGHTS_MANAGER)
    validate_error(refused, "ERR_STALE_DEAL_VERSION", 412)

    untouched = _read_tranche(api, scenario["second"]["id"])
    assert untouched["tranche_state"] == "PENDING"
    assert untouched["confirmed_units"] == 0
    assert untouched["confirmed_at"] is None
    unmoved = _read_deal(api, deal_id)
    assert unmoved["version"] == moved["version"]
    assert unmoved["released_units"] == 20

    replayed = get_success_data(
        api.confirm_release_tranche(scenario["second"]["id"],
                                    confirm_tranche_payload(unmoved["version"], 20),
                                    RIGHTS_MANAGER)
    )
    assert replayed["tranche_state"] == "CONFIRMED"
    settled = _read_deal(api, deal_id)
    assert_version_incremented(settled["version"], unmoved["version"])
    assert_deal_position(settled, released=40, shortfall=0, liability=320000,
                         status="FULLY_RELEASED")


def test_two_sibling_confirmations_racing_on_one_deal_version_leave_one_winner(
    api: ApiClient,
) -> None:
    """Concurrent confirmations of two PENDING siblings pinning the same deal.

    The deal's version is the shared resource, so exactly one confirmation lands
    and the other is a stale-deal-version refusal; the deal ends up with twenty
    released units and one tranche still PENDING.

    PRD §2.6: "A mismatch is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412)."

    PRD §3.2: "First, `released_units` is the total of `confirmed_units` across
    the deal's tranches whose `tranche_state` is `CONFIRMED` or
    `SHORT_CONFIRMED`; tranches that are still `PENDING` and tranches that have
    gone `LAPSED` contribute nothing to it."

    Design: Corner/cross_cutting_complexity_layers/a_second_tranche_confirmation_needs_the_version_the_first_one_produced
    """
    scenario = _two_pending_tranches(api)
    deal_id = scenario["deal"]["id"]
    pinned = deal_version(api, deal_id)

    outcome = assert_exactly_one_succeeds(*run_race(
        lambda: api.confirm_release_tranche(scenario["first"]["id"],
                                            confirm_tranche_payload(pinned, 20),
                                            RIGHTS_MANAGER),
        lambda: api.confirm_release_tranche(scenario["second"]["id"],
                                            confirm_tranche_payload(pinned, 20),
                                            RIGHTS_MANAGER),
    ))
    validate_error(outcome["failures"][0], "ERR_STALE_DEAL_VERSION", 412)

    final = _read_deal(api, deal_id)
    assert_version_incremented(final["version"], pinned)
    assert final["released_units"] == 20, (
        "only the winning confirmation contributed to the released quantity"
    )
    states = sorted(_read_tranche(api, tranche["id"])["tranche_state"]
                    for tranche in (scenario["first"], scenario["second"]))
    assert states == ["CONFIRMED", "PENDING"]


# --------------------------------------------------------------------------
# A re-price under the director's feet
# --------------------------------------------------------------------------


def _re_priced_package(api: ApiClient) -> Dict[str, Any]:
    """A PRICED package whose price was reviewed and then quietly doubled.

    The fixture carries a committed ticket deal so that publication's supply
    precondition holds, and the second component nearly doubles the list price,
    so approving the superseded version would approve a number nobody read.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)
    package = make_bronze_package(api, event["id"])
    add_component(api, package["id"], **_BRONZE_LINE)
    reviewed = price_package(api, package["id"])
    assert reviewed["list_price_cents"] == 120000

    add_component(api, package["id"], component_type="EXPERIENCE",
                  descriptor="Trophy-room access", quantity=1,
                  unit_cost_cents=50000, markup_pct=1.0000, sequence_no=2)
    superseded = price_package(api, package["id"])
    return {
        "event": event,
        "deal": deal,
        "reviewed": reviewed,
        "superseded": superseded,
    }


def test_a_re_price_self_loop_invalidates_the_version_the_director_reviewed(
    api: ApiClient,
) -> None:
    """The status is PRICED before and after, so only the version can catch it.

    Re-pricing leaves the package exactly where it was in the lifecycle while
    advancing its version and rewriting its money: the list price goes from
    120000 to 220000 on a base of 150000, a margin of 0.3182. Publishing the
    reviewed-but-superseded version is refused with a stale-package-version
    failure that a status-only guard would have admitted, and the refusal leaves
    the package PRICED, unpublished and priced at the new figure. Publishing the
    current version then approves exactly the number that is on the record.

    PRD §2.6: "Publishing a package requires `expected_package_product_version`
    in the request body, a required field whose value must equal the package's
    current `version`."

    PRD §2.6: "A mismatch is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412)
    — most commonly because a re-price intervened and cleared the previous
    approval."

    PRD §3.4: "When all of that holds, `package_status` becomes `PUBLISHED`,
    `published_by_user_id` is stamped with the acting user, `published_at` is
    stamped with the logical clock, and the package's `version` increases by one
    again."

    Design: Corner/cross_cutting_complexity_layers/a_re_price_invalidates_the_exact_price_the_director_was_approving
    """
    scenario = _re_priced_package(api)
    reviewed = scenario["reviewed"]
    superseded = scenario["superseded"]

    assert superseded["package_status"] == "PRICED", (
        "re-pricing is a self-loop: the lifecycle position does not move"
    )
    assert_version_incremented(superseded["version"], reviewed["version"])
    assert_package_pricing(superseded, base_cost=150000, subtotal=220000,
                           list_price=220000, margin_pct=0.3182)

    refused = api.publish_package_product(superseded["id"],
                                          publish_payload(reviewed["version"]),
                                          COMMERCIAL_DIRECTOR)
    validate_error(refused, "ERR_STALE_PACKAGE_VERSION", 412)

    untouched = _read_package(api, superseded["id"])
    assert untouched["package_status"] == "PRICED"
    assert untouched["version"] == superseded["version"]
    assert untouched["published_by_user_id"] is None
    assert untouched["list_price_cents"] == 220000

    published = get_success_data(
        api.publish_package_product(superseded["id"],
                                    publish_payload(untouched["version"]),
                                    COMMERCIAL_DIRECTOR)
    )
    assert published["package_status"] == "PUBLISHED"
    assert published["list_price_cents"] == 220000
    assert_version_incremented(published["version"], untouched["version"])


def test_the_stale_package_version_outranks_the_duties_refusal_it_also_earns(
    api: ApiClient,
) -> None:
    """One request breaks two rules; version pinning is the earlier check.

    The operator who priced the package tries to approve it as well, and does so
    on the version they read before their own re-price. Both the version pin and
    the segregation of duties are violated, and because version pinning is
    evaluated at step six while segregation of duties sits inside operational
    safety at step eight, the answer is the 412 and not the 403. Repairing only
    the version then exposes the second violation on its own.

    PRD §2.7: "**Version pinning**, in the order block, deal, package:
    `ERR_STALE_BLOCK_VERSION`, then `ERR_STALE_DEAL_VERSION`, then
    `ERR_STALE_PACKAGE_VERSION`."

    PRD §2.7: "**Operational safety**, in the order: hospitality readiness for
    credentialing (`ERR_BUILD_NOT_READY`), segregation of duties at publication
    (`ERR_SEGREGATION_OF_DUTIES`), critical fulfillment risk at booking creation
    (`ERR_EVENT_RISK_CRITICAL`)."

    PRD §3.4: "The acting `X-User-ID` must differ from the package's
    `priced_by_user_id`: the operator who set a price may never be the operator
    who approves it, and an attempt to do both is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/cross_cutting_complexity_layers/a_re_price_invalidates_the_exact_price_the_director_was_approving
    """
    scenario = _re_priced_package(api)
    reviewed = scenario["reviewed"]
    superseded = scenario["superseded"]

    both_broken = api.publish_package_product(superseded["id"],
                                              publish_payload(reviewed["version"]),
                                              COMMERCIAL_DIRECTOR_AS_PRICER)
    validate_error(both_broken, "ERR_STALE_PACKAGE_VERSION", 412)

    only_duties = api.publish_package_product(superseded["id"],
                                              publish_payload(superseded["version"]),
                                              COMMERCIAL_DIRECTOR_AS_PRICER)
    validate_error(only_duties, "ERR_SEGREGATION_OF_DUTIES", 403)

    still_priced = _read_package(api, superseded["id"])
    assert still_priced["package_status"] == "PRICED"
    assert still_priced["published_by_user_id"] is None
    assert still_priced["version"] == superseded["version"]


# --------------------------------------------------------------------------
# The guarantee surcharge ladder, which runs downward
# --------------------------------------------------------------------------


def _three_boundary_packages(api: ApiClient) -> Dict[str, Any]:
    """Three single-ticket packages listing 999999, 1000000 and 5000000 cents.

    The fixture's deal is committed with nothing released, so it is exposed for
    every booking, and each package carries one ticket so that the volume ladder
    stays silent and the surcharge is the only moving part.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)

    specs = (
        ("Just Under", "Halfway-line single", 333333, 2.0000, 999999),
        ("Exactly One Million", "Directors' box single", 500000, 1.0000, 1000000),
        ("Exactly Five Million", "Presidential suite single", 2500000, 1.0000, 5000000),
    )
    packages = {}
    for name, descriptor, unit_cost, markup, expected_list in specs:
        package = make_bronze_package(api, event["id"], name=name,
                                      tickets_per_package=1)
        add_component(api, package["id"], component_type="TICKET",
                      descriptor=descriptor, quantity=1,
                      unit_cost_cents=unit_cost, markup_pct=markup,
                      sequence_no=1)
        priced = price_package(api, package["id"])
        assert priced["list_price_cents"] == expected_list, name
        packages[name] = publish_package(api, priced["id"], priced["version"])

    client = make_client(api)
    return {"event": event, "deal": deal, "packages": packages, "client": client}


def test_the_guarantee_surcharge_rate_steps_down_at_its_two_money_thresholds(
    api: ApiClient,
) -> None:
    """A one-cent step across the lower threshold cuts the rate, not raises it.

    Every booking is for a single unit, so the volume band is 0.0000 and the
    discounted subtotal is the list price itself. At 999999 cents the subtotal is
    below the first threshold and attracts the highest rate, 0.0500, for a
    surcharge of 50000; one cent higher, at exactly 1000000, the inclusive
    comparison bites and the rate drops to 0.0350 for 35000 — a 15000-cent swing
    off a one-cent difference. At exactly 5000000 it drops again to 0.0200 for
    100000 rather than staying at 0.0350. The CORPORATE commission is 3 percent of
    the same subtotal throughout, so nothing else moves.

    PRD §3.5: "Where one does, the surcharge rate runs *inversely* to size,
    because larger bookings carry a smaller guarantee load per cent: 0.0200 when
    `discounted_subtotal_cents` is at least 5,000,000 cents, otherwise 0.0350 when
    it is at least 1,000,000 cents, otherwise 0.0500."

    PRD §3.5: "Exposure means the package's fixture has at least one rights deal
    for `TICKET` inventory whose `deal_status` is `COMMITTED`,
    `PARTIALLY_RELEASED` or `SHORTFALL_DECLARED` and whose `released_units` is
    strictly below its `contracted_units`."

    Design: Corner/cross_cutting_complexity_layers/the_guarantee_surcharge_rate_steps_exactly_at_its_two_money_thresholds
    """
    scenario = _three_boundary_packages(api)
    assert scenario["deal"]["deal_status"] == "COMMITTED"
    assert scenario["deal"]["released_units"] == 0
    client_id = scenario["client"]["id"]

    low = make_booking(api, client_id, scenario["packages"]["Just Under"]["id"],
                       channel="CORPORATE", units=1)
    middle = make_booking(api, client_id,
                          scenario["packages"]["Exactly One Million"]["id"],
                          channel="CORPORATE", units=1)
    high = make_booking(api, client_id,
                        scenario["packages"]["Exactly Five Million"]["id"],
                        channel="CORPORATE", units=1)

    assert_fraction_4dp(low["volume_discount_pct"], 0.0000)
    assert_booking_price_buildup(low, gross=999999, volume_discount_pct=0.0000,
                                 discounted_subtotal=999999, commission=30000,
                                 surcharge=50000, net=1019999)
    assert_booking_price_buildup(middle, gross=1000000, volume_discount_pct=0.0000,
                                 discounted_subtotal=1000000, commission=30000,
                                 surcharge=35000, net=1005000)
    assert_booking_price_buildup(high, gross=5000000, volume_discount_pct=0.0000,
                                 discounted_subtotal=5000000, commission=150000,
                                 surcharge=100000, net=4950000)

    assert middle["guarantee_surcharge_cents"] < low["guarantee_surcharge_cents"], (
        "the ladder runs downward: a larger subtotal attracts a smaller rate"
    )
    assert high["guarantee_surcharge_cents"] != 175000, (
        "175000 is 0.0350 of 5000000, the figure an exclusive comparison at the "
        "upper threshold would give"
    )
    assert middle["guarantee_surcharge_cents"] != 50000, (
        "50000 is 0.0500 of 1000000, the figure an exclusive comparison at the "
        "lower threshold would give"
    )


# --------------------------------------------------------------------------
# Nothing rolls over until the operations run says so
# --------------------------------------------------------------------------


def _overdue_but_unswept(api: ApiClient) -> Dict[str, Any]:
    """One promise and one installment, both registered before any time passes.

    The deal is exposed, so the five-unit booking nets 587520 and its schedule is
    176256 / 235008 / 176256. The promise falls due 2026-09-01 and the first
    installment 2026-08-04, so moving the clock to 2026-10-05 leaves both of them
    well past their dates without any sweep having run.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)
    tranche = make_tranche(api, deal["id"], promised_units=20,
                           promised_release_at="2026-09-01T00:00:00.000Z")
    package = _publish_bronze(api, event["id"])
    client = make_client(api)
    booking = make_booking(api, client["id"], package["id"],
                           channel="CORPORATE", units=5)
    lines = installments_of(api, booking["id"])
    return {
        "event": event,
        "deal": deal,
        "tranche": tranche,
        "package": package,
        "client": client,
        "booking": booking,
        "lines": lines,
    }


def test_nothing_rolls_over_until_the_operations_run_says_so(
    api: ApiClient,
) -> None:
    """Five weeks past a promise and two months past a due date, nothing moved.

    Both obligations are registered when they are created: the tranche opens
    PENDING against its promised date and the schedule opens SCHEDULED against
    dates derived from the fixture. The clock is then advanced past both, and
    every affected row is re-read and shown untouched — the tranche is still
    PENDING with no lapse stamp, the installment is still SCHEDULED, the client is
    still ACTIVE with nothing overdue, and the booking still reports UNPAID rather
    than some lateness invented on read. One sweep then applies all of it at once,
    stamping the lapse with the run's own clock rather than the promised date. A
    further two months without a run adds nothing, even though the second
    installment's due date has passed in the meantime.

    PRD §2.4: "Setting the clock recomputes nothing on its own; it merely changes
    what every subsequent rule observes."

    PRD §3.2: "During the operations rollover sweep, every tranche that is still
    `PENDING` whose `promised_release_at` is strictly earlier than the logical
    clock, and whose deal is neither `SETTLED` nor `TERMINATED`, moves `PENDING →
    LAPSED`: `lapsed_at` is stamped, `confirmed_units` stays at 0, the parent
    deal's `version` increases by one, the deal status function re-runs (and may
    declare shortfall exactly as above), and the fixture's
    `fulfillment_risk_score` and `risk_posture` are recomputed."

    PRD §3.6: "Second it ages money: every `SCHEDULED` installment whose `due_at`
    is now behind the logical clock moves `SCHEDULED → OVERDUE` and has its
    `days_overdue` recomputed as the whole days between its `due_at` and the
    logical clock; an installment that is not `OVERDUE` reports `days_overdue` as
    0."

    PRD §3.6: "No credit-standing state is terminal, and only the rollover moves
    `client_status`."

    Design: Corner/cross_cutting_complexity_layers/nothing_rolls_over_until_the_operations_run_says_so
    """
    scenario = _overdue_but_unswept(api)
    deal_id = scenario["deal"]["id"]
    tranche_id = scenario["tranche"]["id"]
    client_id = scenario["client"]["id"]
    booking_id = scenario["booking"]["id"]
    first_line = scenario["lines"][0]

    assert scenario["tranche"]["tranche_state"] == "PENDING"
    assert scenario["tranche"]["promised_release_at"] == "2026-09-01T00:00:00.000Z"
    assert scenario["booking"]["net_price_cents"] == 587520
    assert_schedule_amounts(scenario["lines"], [176256, 235008, 176256])
    assert first_line["due_at"] == "2026-08-04T00:00:00.000Z"
    assert first_line["installment_state"] == "SCHEDULED"

    set_clock(api, "2026-10-05T00:00:00Z")

    assert _read_tranche(api, tranche_id)["tranche_state"] == "PENDING"
    assert _read_tranche(api, tranche_id)["lapsed_at"] is None
    stale_line = get_success_data(
        api.get_payment_installment(first_line["id"], FINANCE_CONTROLLER)
    )
    assert stale_line["installment_state"] == "SCHEDULED"
    stale_client = read_client(api, client_id)
    assert stale_client["client_status"] == "ACTIVE"
    assert stale_client["overdue_installment_count"] == 0
    assert_deal_position(_read_deal(api, deal_id), released=0, shortfall=20,
                         liability=96000, status="COMMITTED")
    assert read_booking(api, booking_id)["payment_status"] == "UNPAID"

    report = daily_run(api)
    assert_daily_run_report(report, lapsed=1, overdue=1, shortfall=1,
                            client_changes=1)

    lapsed = _read_tranche(api, tranche_id)
    assert lapsed["tranche_state"] == "LAPSED"
    assert lapsed["lapsed_at"] == "2026-10-05T00:00:00.000Z", (
        "the lapse is stamped with the run's clock, not with the promised date"
    )
    aged_line = get_success_data(
        api.get_payment_installment(first_line["id"], FINANCE_CONTROLLER)
    )
    assert aged_line["installment_state"] == "OVERDUE"
    held = read_client(api, client_id)
    assert held["client_status"] == "ON_HOLD"
    assert held["overdue_installment_count"] == 1
    assert_deal_position(_read_deal(api, deal_id), released=0, shortfall=20,
                         liability=96000, status="SHORTFALL_DECLARED")

    set_clock(api, "2026-12-01T00:00:00Z")
    unchanged = read_client(api, client_id)
    assert unchanged["client_status"] == "ON_HOLD"
    assert unchanged["overdue_installment_count"] == 1, (
        "the second installment's due date has passed, but no run has observed it"
    )
    assert _read_tranche(api, tranche_id)["lapsed_at"] == "2026-10-05T00:00:00.000Z"
