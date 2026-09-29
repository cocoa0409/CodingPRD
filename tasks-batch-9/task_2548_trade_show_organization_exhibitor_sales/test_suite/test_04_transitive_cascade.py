"""Multi-level cascades: one write, several entities away."""

from test_helpers import (
    ApiClient,
    BoothStatus,
    CancellationReason,
    DealStatus,
    ExhibitorStatus,
    FloorPosture,
    FulfillmentStatus,
    ObligationStatus,
    PriorityTier,
    ServiceOrderStatus,
    ShowStatus,
    SpaceContractStatus,
    VenueContractStatus,
    ViolationStatus,
    assert_deposit_conservation,
    assert_penalty_points_never_clamped,
    assert_show_area_ledger,
    factories as f,
    fixtures as fx,
    make_floor_manager_headers,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)


def _terminable_env(client: ApiClient) -> dict:
    """A signed 400 sqft contract carrying one advance freight order."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    offered = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    env["contract"] = fx.sign_contract(client, offered, 400000)
    env["service_order"] = fx.service_order(
        client, env["contract"]["id"], env["exhibitor_headers"],
        service_type="MATERIAL_HANDLING", quantity=6,
        ordered_at="2027-02-01T09:00:00Z",
    )
    return env


def _terminate(client: ApiClient, venue_contract_id: str) -> dict:
    current = fx.get_success_data(
        client.get_venue_contract(venue_contract_id, fx.DIRECTOR_HEADERS)
    )
    return validate_success(
        client.terminate_venue_contract(
            venue_contract_id,
            f.terminate_payload(current["version"], "2026-09-01",
                                reason="Hall condemned after the roof survey"),
            fx.DIRECTOR_HEADERS,
        )
    )


def test_terminating_the_agreement_cancels_the_edition_and_waives_the_fee(
    client: ApiClient,
):
    """
    A termination two levels above a signed contract.

    "every show whose `venue_contract_id` is this agreement and whose status is
    `PLANNING`, `SPACE_SELECTION`, `SELLING` or `ON_SITE` is transitioned to
    `CANCELLED` with its `cancellation_reason` set to the literal
    `VENUE_CONTRACT_TERMINATED`".  "Every space contract of the show that is
    `OFFERED`, `COUNTERED` or `SIGNED` transitions to `CANCELLED` with
    `cancellation_reason` `SHOW_CANCELLED` and `cancellation_fee_cents` forced to
    zero".

    Design: Difficulty/transitive_cascade/venue_termination_cascades_four_levels_to_booth_and_service_order_release
    """
    env = _terminable_env(client)

    terminated = _terminate(client, env["venue_contract"]["id"])
    assert terminated["status"] == VenueContractStatus.TERMINATED
    assert terminated["terminated_effective_date"] == "2026-09-01"

    show = fx.read_show(client, env["show"]["id"])
    assert show["status"] == ShowStatus.CANCELLED
    assert show["cancellation_reason"] == CancellationReason.VENUE_CONTRACT_TERMINATED

    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["status"] == SpaceContractStatus.CANCELLED
    assert contract["cancellation_reason"] == CancellationReason.SHOW_CANCELLED
    assert contract["cancellation_fee_cents"] == 0
    assert contract["fee_applied_to_deposit_cents"] == 0
    assert contract["refund_cents"] == 400000
    assert contract["balance_due_cents"] == 0
    assert_deposit_conservation(contract)


def test_the_termination_reaches_the_booths_the_order_and_the_points(
    client: ApiClient,
):
    """
    The two links the request never names: the booth row and the service order.

    "The first releases inventory: every booth of the contract transitions
    `ASSIGNED → AVAILABLE` with `space_contract_id` cleared. The second releases
    services: every service order of the contract whose `status` is `SUBMITTED`
    transitions to `CANCELLED`. The third releases points: `points_awarded` is
    subtracted from the exhibitor's space-point base and then reset to zero".  "A
    cancelled order keeps the `line_total_cents` it was priced at, for the record".

    Design: Difficulty/transitive_cascade/venue_termination_cascades_four_levels_to_booth_and_service_order_release
    """
    env = _terminable_env(client)
    _terminate(client, env["venue_contract"]["id"])

    held = fx.read_booth(client, env["booth_by_number"]["A100"]["id"])
    assert held["status"] == BoothStatus.AVAILABLE
    assert held["space_contract_id"] is None
    untouched = fx.read_booth(client, env["booth_by_number"]["C050"]["id"])
    assert untouched["status"] == BoothStatus.AVAILABLE

    orders, _ = validate_paginated(
        client.list_service_orders(env["contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert len(orders) == 1
    assert orders[0]["status"] == ServiceOrderStatus.CANCELLED
    assert orders[0]["line_total_cents"] == 42240

    assert fx.read_contract(client, env["contract"]["id"])["points_awarded"] == 0
    exhibitor = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert exhibitor["provisional_priority_points"] == 0
    assert exhibitor["certified_priority_points"] == 0
    assert exhibitor["priority_tier"] == PriorityTier.BRONZE

    show = fx.read_show(client, env["show"]["id"])
    assert_show_area_ledger(show, sellable=600, held=0, assigned=0, available=600,
                            committed_ratio_pct=0)
    assert show["floor_posture"] == FloorPosture.OPEN


def _sponsorship_env(client: ApiClient) -> dict:
    """A signed two-obligation deal on an exhibitor sitting one point into SILVER."""
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    env["package"] = fx.sponsorship_package(
        client, env["show"]["id"], package_code="ENTRY_ARCH",
        list_price_cents=700000, price_floor_cents=500000, inventory_total=2,
        exclusivity_category="OUTDOOR_FURNITURE",
        obligation_codes=["LOGO_ON_ENTRY_ARCH", "BAG_INSERT"],
        priority_point_value=12,
    )
    env["exhibitor"] = fx.exhibitor_with_ledger_points(
        client, 590, "Nordic Furnishings",
        "Twelve consecutive editions of loyalty credit", consecutive_years=6,
    )
    env["deal"] = fx.signed_deal(client, env["package"]["id"],
                                 env["exhibitor"]["id"], 600000)
    env["obligations"] = fx.read_obligations(client, env["deal"]["id"])
    return env


def _resolve(client: ApiClient, deal_id: str, obligation_id: str) -> dict:
    return validate_success(
        client.resolve_obligation(
            deal_id, obligation_id, f.resolve_obligation_payload("DELIVERED"),
            make_floor_manager_headers("u_floor_1"),
        )
    )


def test_the_first_of_two_deliveries_stops_short_of_the_credit(client: ApiClient):
    """
    Link one of the chain fires on its own without reaching the tier threshold.

    "A sponsorship deal's contribution is its `negotiated_price_cents` divided by
    five hundred thousand cents — one point for every five thousand dollars of
    sponsorship spend — with the remainder discarded."  "All three of these are
    derived moves that leave `deal_status` untouched and increment only the deal's
    `version` — except on the two edges that arrive at `COMPLETE`, which
    additionally carry the fulfillment credit."

    Design: Difficulty/transitive_cascade/last_obligation_delivery_cascades_to_priority_tier_upgrade
    """
    env = _sponsorship_env(client)
    before = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert before["provisional_priority_points"] == 591
    assert before["priority_tier"] == PriorityTier.SILVER

    _resolve(client, env["deal"]["id"], env["obligations"][0]["id"])

    deal = fx.read_deal(client, env["deal"]["id"])
    assert deal["fulfillment_status"] == FulfillmentStatus.PARTIAL
    assert deal["resolved_obligation_count"] == 1
    assert deal["fulfillment_credited"] is False

    after = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert after["sponsorship_fulfillment_points"] == 0
    assert after["provisional_priority_points"] == 591
    assert after["priority_tier"] == PriorityTier.SILVER


def test_the_last_delivery_credits_the_package_and_lifts_the_tier(client: ApiClient):
    """
    Link two completes the delivery axis and link three crosses the GOLD floor.

    "when `fulfillment_credited` is false, the package's `priority_point_value` is
    added to the exhibitor's `sponsorship_fulfillment_points`, `fulfillment_credited`
    is set to true, and the exhibitor's `provisional_priority_points` and
    `priority_tier` are recomputed from the new total".  "`priority_tier` is a band
    over the *provisional* number: `PLATINUM` at 1000 points or more, `GOLD` at 600
    or more, `SILVER` at 300 or more, and `BRONZE` below that."

    Design: Difficulty/transitive_cascade/last_obligation_delivery_cascades_to_priority_tier_upgrade
    """
    env = _sponsorship_env(client)
    deal_id = env["deal"]["id"]
    _resolve(client, deal_id, env["obligations"][0]["id"])

    last = _resolve(client, deal_id, env["obligations"][1]["id"])
    assert last["status"] == ObligationStatus.DELIVERED

    deal = fx.read_deal(client, deal_id)
    assert deal["fulfillment_status"] == FulfillmentStatus.COMPLETE
    assert deal["resolved_obligation_count"] == 2
    assert deal["fulfillment_credited"] is True

    exhibitor = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert exhibitor["sponsorship_fulfillment_points"] == 12
    assert exhibitor["provisional_priority_points"] == 603
    assert exhibitor["priority_tier"] == PriorityTier.GOLD
    assert exhibitor["ledger_points"] == 590


def _breach_env(client: ApiClient) -> dict:
    """
    An on-site edition carrying a signed contract, one upheld conduct citation
    worth fifteen points, and a signed deal with one obligation still pending.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    env["package"] = fx.sponsorship_package(
        client, show_id, package_code="ENTRY_ARCH", list_price_cents=700000,
        price_floor_cents=500000, inventory_total=2,
        exclusivity_category="OUTDOOR_FURNITURE",
        obligation_codes=["LOGO_ON_ENTRY_ARCH", "BAG_INSERT"],
        priority_point_value=12,
    )
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    offered = fx.offered_contract(
        client, show_id, exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    env["contract"] = fx.sign_contract(client, offered, 400000)

    env["deal"] = fx.signed_deal(client, env["package"]["id"], exhibitor["id"],
                                 600000)
    env["obligations"] = fx.read_obligations(client, env["deal"]["id"])
    _resolve(client, env["deal"]["id"], env["obligations"][0]["id"])

    fx.transition(client, show_id, ShowStatus.SELLING)
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    env["citation"] = fx.upheld_citation(
        client, env["contract"]["id"],
        make_floor_manager_headers("u_floor_1"),
        fx.make_director_headers("u_dir_1"),
        violation_type="SALES_CONDUCT",
        notes="Selling retail off the booth floor during buyer hours",
    )
    return env


def test_closing_the_edition_sweeps_the_pending_obligation_into_a_breach(
    client: ApiClient,
):
    """
    One close transition, two levels down: obligation then deal.

    "Then every `FulfillmentObligation` still `PENDING` whose deal is `SIGNED`
    transitions `PENDING → MISSED`, processed in `created_at` ascending order, and
    each of those transitions bubbles its deal to `BREACHED`".  "if any obligation
    of the deal has a `status` of `MISSED` the value is `BREACHED` — a single missed
    obligation cannot be papered over by waiving the rest".

    Design: Difficulty/transitive_cascade/show_close_cascades_missed_obligation_into_exhibitor_suspension
    """
    env = _breach_env(client)
    before = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert before["penalty_points"] == 15
    assert before["status"] == ExhibitorStatus.ACTIVE
    assert (
        fx.read_deal(client, env["deal"]["id"])["fulfillment_status"]
        == FulfillmentStatus.PARTIAL
    )

    show = fx.transition(client, env["show"]["id"], ShowStatus.CLOSED)
    assert show["status"] == ShowStatus.CLOSED
    assert show["upheld_violation_count"] == 1

    assert (
        fx.read_contract(client, env["contract"]["id"])["status"]
        == SpaceContractStatus.CLOSED_OUT
    )
    rows = {row["id"]: row for row in fx.read_obligations(client, env["deal"]["id"])}
    assert rows[env["obligations"][0]["id"]]["status"] == ObligationStatus.DELIVERED
    assert rows[env["obligations"][1]["id"]]["status"] == ObligationStatus.MISSED

    deal = fx.read_deal(client, env["deal"]["id"])
    assert deal["fulfillment_status"] == FulfillmentStatus.BREACHED
    assert deal["deal_status"] == DealStatus.SIGNED


def test_the_breach_penalty_lands_on_a_pre_loaded_threshold_and_suspends(
    client: ApiClient,
):
    """
    The last link fires only because an earlier, unrelated citation pre-loaded the
    penalty counter.

    "Breach costs the sponsor twenty penalty points, added to its `penalty_points`;
    then `provisional_priority_points`, `certified_priority_points` and
    `priority_tier` are all recomputed, and if the accumulated `penalty_points` has
    reached thirty the exhibitor transitions `ACTIVE → SUSPENDED` in the same pass."
    "sets the citation's `penalty_points` from the penalty schedule: ten for
    `BOOTH_HEIGHT`, five for `NOISE`, eight for `AISLE_ENCROACHMENT` and fifteen for
    `SALES_CONDUCT`."

    Design: Difficulty/transitive_cascade/show_close_cascades_missed_obligation_into_exhibitor_suspension
    """
    env = _breach_env(client)
    fx.transition(client, env["show"]["id"], ShowStatus.CLOSED)

    exhibitor = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert_penalty_points_never_clamped(exhibitor, 35)
    assert exhibitor["status"] == ExhibitorStatus.SUSPENDED
    assert exhibitor["provisional_priority_points"] == 0
    assert exhibitor["certified_priority_points"] == 0
    assert exhibitor["priority_tier"] == PriorityTier.BRONZE

    citations, _ = validate_paginated(
        client.list_rule_violations(env["contract"]["id"], fx.DIRECTOR_HEADERS)
    )
    citation = next(row for row in citations if row["id"] == env["citation"]["id"])
    assert citation["penalty_points"] == 15
    assert citation["status"] == ViolationStatus.UPHELD
