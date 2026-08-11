"""Cold-chain custody roll-ups, the breach budgets, and the three quality dispositions."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    disposition_lot,
    log_leg,
    make_quality_officer_headers,
    read_delivery,
    read_lot,
    read_member,
    read_season,
    read_sub_lot,
    read_subscription,
    setup_fleet,
    setup_hub_box_packed,
    setup_landed_lot,
    setup_open_season,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]


def _clear_landed_lot():
    """A landed 5.00 lb SALMON lot standing in quality_status CLEAR."""
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    ctx.update(fleet)
    ctx.update(setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00))
    return ctx


def test_a_leg_of_exactly_twenty_minutes_stays_inside_the_single_excursion_budget(api):
    """PRD 3.6: "Two budgets are then tested, and both breach on a strict excess so that a
    figure sitting exactly on the budget is still inside it. The single-excursion budget,
    `COLD_CHAIN_SINGLE_EXCURSION_MAX_MIN`, is 20 minutes and is tested against *this* leg's own
    `minutes_above_threshold`."
    PRD 3.6: "The leg's `breach_type` is `BOTH` when both are exceeded, `SINGLE_EXCURSION` when
    only the leg's own figure is, `CUMULATIVE` when only the running total is, and `NONE` when
    neither is."

    Design: Difficulty/boundary_precision_check/single_excursion_boundary_twenty_inside_twentyone_breaches
    """
    ctx = _clear_landed_lot()

    first = log_leg(ctx["lot_id"], "DOCK_TO_HUB", 20, 5.0)
    assert first["breach_type"] == "NONE"

    lot = read_lot(ctx["lot_id"])
    assert lot["quality_status"] == "CLEAR"
    assert lot["cold_chain_cumulative_minutes"] == 20
    assert lot["cold_chain_max_single_minutes"] == 20


def test_a_leg_of_twenty_one_minutes_breaches_and_puts_the_lot_on_hold(api):
    """PRD 3.6: "Logging a leg refreshes three roll-ups on the parent lot across every leg ever
    logged against it, this one included: `cold_chain_cumulative_minutes` is the sum of
    `minutes_above_threshold`, `cold_chain_max_single_minutes` is the largest single such
    figure, and the lot's `peak_temp_c` is the highest `peak_temp_c` any leg reached."
    PRD 3.6: "The cumulative budget, `COLD_CHAIN_CUMULATIVE_BUDGET_MIN`, is 45 minutes and is
    tested against the refreshed `cold_chain_cumulative_minutes`."
    PRD 3.6: "Any `breach_type` other than `NONE` moves the lot's quality axis `CLEAR → HOLD`"

    Design: Difficulty/boundary_precision_check/single_excursion_boundary_twenty_inside_twentyone_breaches
    """
    ctx = _clear_landed_lot()

    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 20, 5.0)
    second = log_leg(ctx["lot_id"], "HUB_HOLD", 21, 6.5)
    assert second["breach_type"] == "SINGLE_EXCURSION"

    lot = read_lot(ctx["lot_id"])
    assert lot["cold_chain_cumulative_minutes"] == 41
    assert lot["cold_chain_max_single_minutes"] == 21
    assert float(lot["peak_temp_c"]) == pytest.approx(6.5)
    assert lot["quality_status"] == "HOLD"


def test_the_officer_who_logged_the_breach_may_not_clear_it(api):
    """PRD 3.6: "The segregation gate then asks who is signing: the acting `X-User-ID` must
    differ from the `recorded_by_user_id` of every cold-chain leg on this lot whose
    `breach_type` is not `NONE`. An officer who logged the breach may not also clear it, and an
    attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/same_officer_cannot_disposition_a_breach_they_logged
    """
    ctx = _clear_landed_lot()
    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 25, 6.0, headers=make_quality_officer_headers("qo-1"))

    response = api.disposition_lot(
        ctx["lot_id"], {"disposition": "RELEASE"}, make_quality_officer_headers("qo-1")
    )
    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    lot = read_lot(ctx["lot_id"])
    assert lot["quality_status"] == "HOLD"
    assert lot["cold_chain_cumulative_minutes"] == 25


def test_a_release_outside_its_cold_chain_budget_is_refused(api):
    """PRD 3.6: "`RELEASE` requires `cold_chain_cumulative_minutes` to be at most
    `COLD_CHAIN_RELEASE_LIMIT_MIN`, which is 60 minutes, *and* the lot's `peak_temp_c` to be at
    most `QUALITY_RELEASE_TEMP_C`, which is 7.0 degrees Celsius; `DISCOUNT` requires
    `cold_chain_cumulative_minutes` to be at most `COLD_CHAIN_DISCOUNT_LIMIT_MIN`, which is 90
    minutes; and `DISCARD` has no budget test at all, because condemning fish is always
    permissible. A disposition outside its budget is refused with
    `ERR_COLD_CHAIN_BUDGET_EXCEEDED`."

    Design: Corner/validations/release_disposition_beyond_its_cold_chain_budget_is_rejected
    """
    ctx = _clear_landed_lot()
    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 20, 5.0)
    log_leg(ctx["lot_id"], "HUB_HOLD", 76, 11.0)

    response = api.disposition_lot(
        ctx["lot_id"], {"disposition": "RELEASE"}, make_quality_officer_headers("qo-1")
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_COLD_CHAIN_BUDGET_EXCEEDED.value)

    lot = read_lot(ctx["lot_id"])
    assert lot["cold_chain_cumulative_minutes"] == 96
    assert lot["cold_chain_max_single_minutes"] == 76
    assert lot["quality_status"] == "HOLD"


def _discarded_packed_box():
    """A packed hub box whose lot is put on HOLD by a 25 minute breach and then discarded."""
    ctx = setup_hub_box_packed(pool_pounds=5.00, paid_cents=90000)
    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 25, 9.0)
    ctx["disposition"] = disposition_lot(ctx["lot_id"], "DISCARD", officer_user_id="qo-1")
    return ctx


def test_a_discard_destroys_the_consignment_and_voids_the_box_it_carried(api):
    """PRD 3.6: "`DISCARD` moves the quality axis `HOLD → DISCARDED` and starts the longest
    cascade in the system, six hops deep, all inside the one request. The disposition itself is
    hop one. Hop two destroys the physical consignments: every sub-lot of that lot standing in
    `IN_TRANSIT` or `ARRIVED` moves to `DESTROYED`."
    PRD 3.6: "Hop three, caused by hop two, voids the boxes those consignments were carrying:
    every delivery whose `sub_lot_id` names one of them and whose `fulfillment_status` is
    `ALLOCATED`, `PACKED`, `IN_TRANSIT` or `AT_HUB` moves to `VOIDED` with `fill_status` `VOID`,
    and a box that was sitting `AT_HUB` releases the cooler slot it had reserved as it goes."

    Design: Difficulty/transitive_cascade/discard_disposition_six_hop_cascade
    """
    ctx = _discarded_packed_box()

    lot = read_lot(ctx["lot_id"])
    assert lot["quality_status"] == "DISCARDED"
    assert read_sub_lot(ctx["sub_lot_id"])["status"] == "DESTROYED"

    delivery = read_delivery(ctx["delivery_id"])
    assert delivery["fulfillment_status"] == "VOIDED"
    assert delivery["fill_status"] == "VOID"


def test_a_discard_refunds_the_charged_box_and_flags_the_season_shortfall(api):
    """PRD 3.6: "Hop four, caused by hop three, refunds them: each such delivery whose money
    axis stands in `CHARGED` or `PARTIALLY_CREDITED` moves to `REFUNDED` with `credit_cents`
    raised to its full `invoice_total_cents`, that amount is added to the member's
    `credit_balance_cents`, and the owning subscription's `credited_count` rises by 1."
    PRD 3.6: "Hop five, caused by the `credited_count` written in hop four, flags the
    subscription for the season-end reckoning: a subscription whose `true_up_status` is
    `NOT_DUE` moves to `SHORTFALL_FLAGGED`. Hop six, caused by hop five, increments the season's
    `shortfall_flag_count` by 1."

    Design: Difficulty/transitive_cascade/discard_disposition_six_hop_cascade
    """
    ctx = _discarded_packed_box()

    delivery = read_delivery(ctx["delivery_id"])
    assert delivery["billing_status"] == "REFUNDED"
    assert delivery["credit_cents"] == 4500

    assert read_member(ctx["member_id"])["credit_balance_cents"] == 4500

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["credited_count"] == 1
    assert subscription["true_up_status"] == "SHORTFALL_FLAGGED"

    assert read_season(ctx["season_id"])["shortfall_flag_count"] == 1
