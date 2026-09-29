"""Cyclic negotiation and the two independent axes of a sponsorship deal."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    DealStatus,
    FulfillmentStatus,
    ObligationStatus,
    SpaceContractStatus,
    factories as f,
    fixtures as fx,
    make_floor_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)


def _negotiation_setup(client: ApiClient) -> dict:
    """An OFFERED 400 sqft contract with `negotiation_round` still at zero."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    env["contract"] = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    return env


def test_only_the_exhibitors_counters_consume_the_round_budget(client: ApiClient):
    """
    Three counter / re-offer cycles on one contract.

    "It writes `requested_discount_pct` from the request — a percentage from 0
    through 40 — increments `negotiation_round` by one, moves the contract `OFFERED
    → COUNTERED`".  "Critically, a re-offer does **not** increment
    `negotiation_round`: only the exhibitor's counters consume the round budget, so
    the producer can re-offer as often as it likes within three exhibitor
    counters."

    Design: Difficulty/non_linear_state_machine/space_contract_bounded_negotiation_cycle_exhausts_on_fourth_counter
    """
    env = _negotiation_setup(client)
    contract_id = env["contract"]["id"]

    for expected_round in (1, 2, 3):
        countered = validate_success(
            client.negotiate(contract_id, f.counter_payload(8),
                             env["exhibitor_headers"])
        )
        assert countered["status"] == SpaceContractStatus.COUNTERED
        assert countered["negotiation_round"] == expected_round

        reoffered = validate_success(
            client.negotiate(contract_id, f.reoffer_payload(5),
                             fx.SALES_REP_HEADERS)
        )
        assert reoffered["status"] == SpaceContractStatus.OFFERED
        assert reoffered["negotiation_round"] == expected_round
        assert reoffered["approved_discount_pct"] == 5
        assert reoffered["space_fee_cents"] == 1478466


def test_the_fourth_counter_exhausts_the_cycle_and_leaves_the_hold_intact(
    client: ApiClient,
):
    """
    A fourth counter attempted from a legitimately OFFERED contract.

    "A fourth counter, attempted when `negotiation_round` already equals three, is
    refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`; this is the termination
    condition of the cycle."

    Design: Difficulty/non_linear_state_machine/space_contract_bounded_negotiation_cycle_exhausts_on_fourth_counter
    """
    env = _negotiation_setup(client)
    contract_id = env["contract"]["id"]
    for _ in range(3):
        validate_success(
            client.negotiate(contract_id, f.counter_payload(8),
                             env["exhibitor_headers"])
        )
        validate_success(
            client.negotiate(contract_id, f.reoffer_payload(5),
                             fx.SALES_REP_HEADERS)
        )

    validate_error(
        client.negotiate(contract_id, f.counter_payload(8),
                         env["exhibitor_headers"]),
        ApiErrorId.NEGOTIATION_ROUNDS_EXHAUSTED,
        422,
    )

    contract = fx.read_contract(client, contract_id)
    assert contract["status"] == SpaceContractStatus.OFFERED
    assert contract["negotiation_round"] == 3
    booth = fx.read_booth(client, env["booth_by_number"]["A100"]["id"])
    assert booth["status"] == BoothStatus.HELD
    assert fx.read_show(client, env["show"]["id"])["held_net_sqft"] == 400


def _deal_setup(client: ApiClient) -> dict:
    """A signed sponsorship with two obligations, on an edition still in PLANNING."""
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    env["package"] = fx.sponsorship_package(
        client, env["show"]["id"], package_code="ENTRY_ARCH",
        list_price_cents=700000, price_floor_cents=500000, inventory_total=2,
        exclusivity_category="OUTDOOR_FURNITURE",
        obligation_codes=["LOGO_ON_ENTRY_ARCH", "BAG_INSERT"],
        priority_point_value=12,
    )
    env["exhibitor"] = fx.exhibitor(client, "Nordic Furnishings",
                                    consecutive_years=6)
    env["deal"] = fx.signed_deal(client, env["package"]["id"],
                                 env["exhibitor"]["id"], 600000)
    env["obligations"] = fx.read_obligations(client, env["deal"]["id"])
    return env


def test_the_fulfillment_axis_moves_while_the_commercial_axis_stands_still(
    client: ApiClient,
):
    """
    One of two obligations delivered on a signed deal.

    "The derivation of `fulfillment_status` is evaluated in a fixed order, and the
    order is what makes it correct."  "In transition terms, a deal with at least two
    obligations of which between one and all-but-one are resolved and none is missed
    sits at `NOT_STARTED → PARTIAL`"  "All three of these are derived moves that
    leave `deal_status` untouched and increment only the deal's `version`"  "a
    `due_date` set to the show's `event_start` less fourteen days"

    Design: Difficulty/non_linear_state_machine/sponsorship_deal_two_axes_advance_independently
    """
    env = _deal_setup(client)
    deal_id = env["deal"]["id"]
    assert env["deal"]["deal_status"] == DealStatus.SIGNED
    assert env["deal"]["fulfillment_status"] == FulfillmentStatus.NOT_STARTED
    assert env["deal"]["obligation_count"] == 2
    assert env["deal"]["resolved_obligation_count"] == 0
    ob1 = env["obligations"][0]
    assert ob1["due_date"] == "2027-02-19"
    assert ob1["status"] == ObligationStatus.PENDING

    resolved = validate_success(
        client.resolve_obligation(
            deal_id, ob1["id"], f.resolve_obligation_payload("DELIVERED"),
            make_floor_manager_headers("u_floor_1"),
        )
    )
    assert resolved["status"] == ObligationStatus.DELIVERED

    deal = fx.read_deal(client, deal_id)
    assert deal["fulfillment_status"] == FulfillmentStatus.PARTIAL
    assert deal["resolved_obligation_count"] == 1
    assert deal["deal_status"] == DealStatus.SIGNED
    assert deal["fulfillment_credited"] is False
    exhibitor = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert exhibitor["sponsorship_fulfillment_points"] == 0


def test_cancelling_the_deal_leaves_the_fulfillment_axis_where_it_was(
    client: ApiClient,
):
    """
    The commercial axis walks on to `CANCELLED` while the partially fulfilled
    delivery record stands.

    "Cancelling a deal is available to a `ShowDirector` or to the sponsoring
    `Exhibitor` and carries a mandatory `cancellation_reason`, and the same act has
    two shapes — `PROPOSED → CANCELLED` and `SIGNED → CANCELLED`."  "The reason is
    stored and the unit is released as before."  "`fulfillment_status` keeps whatever
    derived value it already had: a commercial cancellation does not rewind the
    delivery axis"

    Design: Difficulty/non_linear_state_machine/sponsorship_deal_two_axes_advance_independently
    """
    env = _deal_setup(client)
    deal_id = env["deal"]["id"]
    ob1, ob2 = env["obligations"][0], env["obligations"][1]
    validate_success(
        client.resolve_obligation(
            deal_id, ob1["id"], f.resolve_obligation_payload("DELIVERED"),
            make_floor_manager_headers("u_floor_1"),
        )
    )

    cancelled = validate_success(
        client.cancel_sponsorship_deal(
            deal_id,
            f.cancel_payload("Sponsor withdrew after the arch was hung"),
            fx.make_director_headers("u_dir_1"),
        )
    )
    assert cancelled["deal_status"] == DealStatus.CANCELLED
    assert cancelled["fulfillment_status"] == FulfillmentStatus.PARTIAL

    rows = {row["id"]: row for row in fx.read_obligations(client, deal_id)}
    assert rows[ob1["id"]]["status"] == ObligationStatus.DELIVERED
    assert rows[ob2["id"]]["status"] == ObligationStatus.PENDING

    packages, _ = validate_paginated(
        client.list_sponsorship_packages(env["show"]["id"], fx.DIRECTOR_HEADERS)
    )
    package = next(p for p in packages if p["id"] == env["package"]["id"])
    assert package["inventory_committed"] == 0
    assert package["inventory_available"] == 2
