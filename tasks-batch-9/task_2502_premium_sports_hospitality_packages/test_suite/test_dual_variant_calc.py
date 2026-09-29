"""Calculations that answer with two different variants over one set of inputs.

Two of them exist in this API: the margin report, whose variant is chosen by the
fixture's status but may be overridden on the query string, and the cancellation
settlement, whose variant is chosen by the fixture's status alone.
"""

from typing import Any, Dict

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    RIGHTS_MANAGER,
    ApiClient,
    allocate_booking,
    assert_fraction_4dp,
    assert_margin_report,
    assert_settlement_identity,
    cancel_booking,
    get_success_data,
    gold_sales_floor,
    installments_of,
    issue_credentials,
    make_booking,
    make_client,
    make_committed_deal,
    make_event,
    make_published_gold_package,
    make_ready_build,
    margin_report,
    read_client,
    read_event,
    release_deal,
    reset_clock,
    set_clock,
)


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------


def _completed_fixture_with_one_delivered_and_one_cancelled_booking(
    api: ApiClient,
) -> Dict[str, Any]:
    """A played fixture carrying exactly one DELIVERED and one CANCELLED sale.

    The 10-unit booking is credentialed and then delivered by completion; the
    5-unit booking is cancelled 184 days out, while the fixture is still
    SCHEDULED, so it retains a TIER_SCHEDULE fee.
    """
    floor = gold_sales_floor(api)
    delivered = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=10)
    allocate_booking(api, delivered["id"], floor["block"]["id"])
    build = make_ready_build(api, floor["event"]["id"])
    issue_credentials(api, delivered["id"])

    walked_away = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=5)
    cancelled = cancel_booking(api, walked_away["id"])

    set_clock(api, "2027-02-01T18:00:00Z")
    get_success_data(api.complete_event(floor["event"]["id"], RIGHTS_MANAGER))

    floor["build"] = build
    floor["delivered"] = delivered
    floor["cancelled"] = cancelled
    return floor


def _two_identical_five_unit_bookings(api: ApiClient) -> Dict[str, Any]:
    """Two CORPORATE bookings of 5 units each on one unallocatable fixture.

    No allocation block is created, so neither booking can ever hold inventory
    and the ticket leg of a cost-recovery settlement is provably zero. The
    ticket deal has released its whole contracted quantity, so neither booking
    carries a guarantee surcharge and the two net prices are identical.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    release_deal(api, deal["id"], 60)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api)
    first = make_booking(api, client["id"], package["id"], units=5)
    second = make_booking(api, client["id"], package["id"], units=5)
    return {
        "event": event,
        "deal": deal,
        "package": package,
        "client": client,
        "first": first,
        "second": second,
    }


# --------------------------------------------------------------------------
# The margin report's two variants
# --------------------------------------------------------------------------


def test_provisional_margin_recognises_every_live_booking_at_full_acquisition_cost(
    api: ApiClient,
) -> None:
    """PROVISIONAL revenue counts live bookings and carries unsold units whole.

    The fixture has been played, so the report defaults to FINAL; asking for
    PROVISIONAL explicitly reads the very same rows on a forward-looking basis.
    The one DELIVERED booking contributes its net price of 1580574, the retained
    cancellation fee contributes nothing, and the 40 unsold released units are
    carried at 8000 cents each for a full 320000 of exposure.

    PRD §3.9: "Under `PROVISIONAL`, `revenue_cents` is the total of
    `net_price_cents` across the fixture's bookings whose `fulfillment_status`
    is `RESERVED`, `ALLOCATED`, `CREDENTIALED`, `DELIVERED` or `REBOOK_PENDING`
    — every live booking is assumed to convert — and `unsold_exposure_cents` is
    the full-cost exposure carried at one hundred percent of acquisition cost."

    Design: Difficulty/dual_variant_calc/margin_report_provisional_vs_final_same_event
    """
    scenario = _completed_fixture_with_one_delivered_and_one_cancelled_booking(api)

    report = margin_report(api, scenario["event"]["id"], "PROVISIONAL")
    assert_margin_report(
        report,
        variant="PROVISIONAL",
        revenue=1580574,
        rights_cost=480000,
        build_cost=220000,
        cost=700000,
        unsold_units=40,
        unsold_exposure=320000,
        margin=880574,
        net_margin=560574,
        margin_pct=0.3547,
    )


def test_final_margin_adds_retained_fees_and_writes_unsold_units_down_by_salvage(
    api: ApiClient,
) -> None:
    """FINAL revenue is delivered net plus retained fees, exposure salvaged.

    Read off the same played fixture, FINAL recognises the DELIVERED booking's
    1580574 plus the CANCELLED booking's retained 82465 fee, and writes the
    320000 of unsold exposure down to 208000 — sixty-five percent of it. The
    shared cost base and unsold unit count are byte-identical to the
    PROVISIONAL response, so only the variant rule can explain the difference.

    PRD §3.9: "Under `FINAL`, `revenue_cents` is the total of `net_price_cents`
    across only the bookings whose `fulfillment_status` is `DELIVERED`, plus the
    total of `cancellation_fee_cents` across the bookings whose
    `fulfillment_status` is `CANCELLED` — realised delivery revenue plus
    retained cancellation fees — and `unsold_exposure_cents` is the full-cost
    exposure written down by the salvage recovery, that is, the full-cost
    exposure multiplied by one less thirty-five percent, rounded half-up to a
    whole cent."

    Design: Difficulty/dual_variant_calc/margin_report_provisional_vs_final_same_event
    """
    scenario = _completed_fixture_with_one_delivered_and_one_cancelled_booking(api)
    event_id = scenario["event"]["id"]

    provisional = margin_report(api, event_id, "PROVISIONAL")
    final = margin_report(api, event_id, "FINAL")

    assert_margin_report(
        final,
        variant="FINAL",
        revenue=1663039,
        rights_cost=480000,
        build_cost=220000,
        cost=700000,
        unsold_units=40,
        unsold_exposure=208000,
        margin=963039,
        net_margin=755039,
        margin_pct=0.4540,
    )

    # The retained fee enters FINAL and only FINAL.
    assert scenario["cancelled"]["cancellation_fee_cents"] == 82465
    assert final["revenue_cents"] - provisional["revenue_cents"] == 82465

    # The salvage write-down is applied in FINAL and only FINAL.
    assert final["unsold_exposure_cents"] == 208000
    assert provisional["unsold_exposure_cents"] == 320000

    # Everything the two variants share is identical.
    for shared in ("rights_cost_cents", "build_cost_cents", "cost_cents", "unsold_units"):
        assert final[shared] == provisional[shared], f"{shared} is shared between variants"

    # And everything they do not share differs.
    for divergent in ("revenue_cents", "unsold_exposure_cents", "margin_cents",
                      "net_margin_cents"):
        assert final[divergent] != provisional[divergent]
    assert final["margin_pct"] != provisional["margin_pct"]


def test_margin_variants_draw_their_two_revenue_figures_from_the_same_two_bookings(
    api: ApiClient,
) -> None:
    """Both revenue rules read one DELIVERED row and one CANCELLED row.

    The booking list confirms the mix the two variants disagree about: the
    10-unit sale is DELIVERED at 1580574 and the 5-unit sale is CANCELLED at
    824647 with a retained fee of 82465. Because the fixture is played, the
    report's default variant is FINAL, which is what an omitted variant returns.

    PRD §3.9: "While the fixture's `status` is `SCHEDULED`, `POSTPONED` or
    `RESCHEDULED` the report defaults to `PROVISIONAL`; once the fixture's
    `status` is `COMPLETED` or `CANCELLED` it defaults to `FINAL`."

    Design: Difficulty/dual_variant_calc/margin_report_provisional_vs_final_same_event
    """
    scenario = _completed_fixture_with_one_delivered_and_one_cancelled_booking(api)

    rows = get_success_data(
        api.list_bookings(CLIENT_SERVICE_AGENT,
                          {"package_product_id": scenario["package"]["id"], "limit": 100})
    )
    by_id = {row["id"]: row for row in rows}
    delivered = by_id[scenario["delivered"]["id"]]
    cancelled = by_id[scenario["cancelled"]["id"]]

    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["net_price_cents"] == 1580574
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["net_price_cents"] == 824647
    assert cancelled["cancellation_fee_cents"] == 82465

    defaulted = margin_report(api, scenario["event"]["id"])
    assert defaulted["variant"] == "FINAL"
    assert defaulted["revenue_cents"] == 1663039
    assert_fraction_4dp(defaulted["margin_pct"], 0.4540)


# --------------------------------------------------------------------------
# The cancellation settlement's two variants
# --------------------------------------------------------------------------


def test_tier_schedule_settlement_scales_the_fee_off_days_to_the_fixture(
    api: ApiClient,
) -> None:
    """A cancellation 184 days out retains the most generous ten percent band.

    The booking's net price is 824647 and the fixture is SCHEDULED, so the
    days-to-event ladder is read and its top band applies: the fee is
    round_half_up(824647 * 0.10) == 82465. Nothing had been paid, so the whole
    fee falls due as a balance.

    PRD §3.8: "The fee percentage is read off a days-to-event ladder in which
    every comparison is inclusive: 0.10 when the fixture is at least 90 days
    away, otherwise 0.25 when it is at least 60 days away, otherwise 0.50 when
    it is at least 30 days away, otherwise 0.80 when it is at least 7 days away,
    otherwise 1.00."

    Design: Difficulty/dual_variant_calc/cancellation_fee_tier_schedule_vs_cost_recovery_same_booking_shape
    """
    scenario = _two_identical_five_unit_bookings(api)
    assert scenario["first"]["net_price_cents"] == 824647
    assert scenario["package"]["base_cost_cents"] == 125072

    settled = cancel_booking(api, scenario["first"]["id"])

    assert settled["settlement_variant"] == "TIER_SCHEDULE"
    assert settled["cancellation_fee_cents"] == 82465
    assert settled["refund_cents"] == 0
    assert settled["balance_due_cents"] == 82465
    assert settled["payment_status"] == "SETTLEMENT_DUE"
    assert settled["fulfillment_status"] == "CANCELLED"
    assert_settlement_identity(settled, pre_paid_cents=0)

    settlement_lines = installments_of(api, scenario["first"]["id"],
                                      installment_kind="SETTLEMENT")
    assert len(settlement_lines) == 1
    assert settlement_lines[0]["amount_cents"] == 82465


def test_cost_recovery_settlement_caps_the_fee_at_irrecoverable_committed_cost(
    api: ApiClient,
) -> None:
    """On a postponed fixture the fee is acquisition cost, not a tier band.

    The second booking is numerically identical to the first — same package,
    same 5 units, same 824647 net, nothing paid — and the only thing that
    changed before it was cancelled is the fixture's status. Its
    `allocation_block_id` is null, so the ticket leg is 0 and the whole fee is
    the non-ticket leg round_half_up(125072 * 5 * 0.20) == 125072, which is
    larger than the most generous tier band.

    PRD §3.8: "The ticket component is 0 where the booking's
    `allocation_block_id` is null, because a booking that was never allocated
    committed no rights-holder inventory; otherwise it is the booking's `units`
    multiplied by the package's `tickets_per_package` multiplied by the
    `unit_cost_cents` of the rights deal reached through that allocation block."

    Design: Difficulty/dual_variant_calc/cancellation_fee_tier_schedule_vs_cost_recovery_same_booking_shape
    """
    scenario = _two_identical_five_unit_bookings(api)
    assert scenario["second"]["net_price_cents"] == 824647

    tier_settled = cancel_booking(api, scenario["first"]["id"])
    get_success_data(api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER))
    cost_settled = cancel_booking(api, scenario["second"]["id"])

    assert cost_settled["settlement_variant"] == "COST_RECOVERY"
    assert cost_settled["cancellation_fee_cents"] == 125072
    assert cost_settled["refund_cents"] == 0
    assert cost_settled["balance_due_cents"] == 125072
    assert cost_settled["payment_status"] == "SETTLEMENT_DUE"
    assert cost_settled["fulfillment_status"] == "CANCELLED"
    assert cost_settled["allocation_block_id"] is None
    assert_settlement_identity(cost_settled, pre_paid_cents=0)

    # The cost-recovery fee is the larger of the two on identical booking data.
    assert cost_settled["cancellation_fee_cents"] > tier_settled["cancellation_fee_cents"]
    assert (cost_settled["cancellation_fee_cents"]
            - tier_settled["cancellation_fee_cents"]) == 42607

    settlement_lines = installments_of(api, scenario["second"]["id"],
                                      installment_kind="SETTLEMENT")
    assert len(settlement_lines) == 1
    assert settlement_lines[0]["amount_cents"] == 125072


def test_the_settlement_variant_is_selected_by_the_fixture_not_by_the_booking(
    api: ApiClient,
) -> None:
    """Only the fixture's status changed between two identical cancellations.

    Both bookings were created in the same shape on the same logical day, and
    the fixture is what moved in between: its status reads POSTPONED with one
    postponement recorded. The client's exposure is the sum of the two
    settlement balances, and its credit standing is untouched because no
    installment has aged.

    PRD §3.8: "The settlement arithmetic has **two variants**, and which one
    applies is decided purely by the fixture's `status` at the moment of
    cancellation."

    Design: Difficulty/dual_variant_calc/cancellation_fee_tier_schedule_vs_cost_recovery_same_booking_shape
    """
    scenario = _two_identical_five_unit_bookings(api)

    first = cancel_booking(api, scenario["first"]["id"])
    get_success_data(api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER))
    second = cancel_booking(api, scenario["second"]["id"])

    assert first["settlement_variant"] == "TIER_SCHEDULE"
    assert second["settlement_variant"] == "COST_RECOVERY"

    fixture = read_event(api, scenario["event"]["id"])
    assert fixture["status"] == "POSTPONED"
    assert fixture["postponement_count"] == 1

    client = read_client(api, scenario["client"]["id"])
    assert client["outstanding_cents"] == 207537
    assert client["client_status"] == "ACTIVE"
