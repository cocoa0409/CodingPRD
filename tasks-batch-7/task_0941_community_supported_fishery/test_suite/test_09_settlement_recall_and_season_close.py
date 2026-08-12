"""Vendor settlement, the quality holdback, product recalls and the season-end true-up."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    arrive_sub_lot,
    assert_same_instant,
    assert_settlement_statement,
    assert_vendor_money_invariant,
    close_landings,
    delivery_of_week,
    disposition_lot,
    finalize_settlement,
    hub_destination,
    log_leg,
    make_member_headers,
    new_hub,
    new_recall,
    new_season,
    new_settlement,
    new_window,
    open_window,
    pack_delivery,
    pickup_delivery,
    read_delivery,
    read_lot,
    read_member,
    read_recall,
    read_season,
    read_settlement,
    read_sub_lot,
    read_subscription,
    run_true_up,
    set_clock,
    setup_fleet,
    setup_landed_lot,
    setup_member_subscription,
    setup_open_season,
    setup_verified_cod_landing,
    split_lot,
    stage_delivery,
    sub_lots_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_a_created_statement_comes_back_provisional_with_the_holdback_withheld(api):
    """PRD 3.9: "The statement is computed inside the create call — `DRAFT` is only the
    pre-computation waypoint, and the statement comes back already in `PROVISIONAL` with its
    `variant` recorded as `PROVISIONAL`."
    PRD 3.9: "While the statement is `PROVISIONAL` the entire holdback is simply withheld:
    `holdback_released_cents`, `holdback_forfeited_cents` and `offset_cents` are all 0, and
    `net_payable_cents` is `gross_cents` less `deductions_cents` less `holdback_cents`."
    PRD 3.9: "`HOLDBACK_PCT` is 0.10, so `holdback_cents` is 10 percent of `gross_cents`,
    rounded half up."

    Design: Difficulty/dual_variant_calc/settlement_holdback_provisional_vs_final
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = validate_success(
        api.create_settlement(
            ctx["trip_id"], {"expected_trip_version": ctx["trip_version"]}, ADMIN
        ),
        201,
    )
    assert_settlement_statement(statement)
    assert statement["status"] == "PROVISIONAL"
    assert statement["variant"] == "PROVISIONAL"
    assert statement["gross_cents"] == 9136
    assert statement["holdback_cents"] == 914
    assert statement["holdback_released_cents"] == 0
    assert statement["holdback_forfeited_cents"] == 0
    assert statement["offset_cents"] == 0
    assert statement["net_payable_cents"] == 6048
    assert float(read_lot(ctx["lot_id"])["landed_pounds_net"]) == pytest.approx(10.04)


def test_finalizing_against_a_clear_lot_releases_the_whole_holdback(api):
    """PRD 3.9: "Finalization resolves the holdback against whatever the lot's quality
    disposition turned out to be, and the `variant` becomes `FINAL`."
    PRD 3.9: "When the lot is `CLEAR` or `RELEASED`, `holdback_released_cents` is the whole
    `holdback_cents`, `holdback_forfeited_cents` is 0 and `offset_cents` is 0."
    PRD 3.9: "Finalized against a `CLEAR` lot it is 6962."

    Design: Difficulty/dual_variant_calc/settlement_holdback_provisional_vs_final
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = new_settlement(ctx["trip_id"], ctx["trip_version"])
    assert statement["net_payable_cents"] == 6048

    finalized = finalize_settlement(statement["id"])
    assert finalized["status"] == "FINAL"
    assert finalized["variant"] == "FINAL"
    assert finalized["gross_cents"] == 9136
    assert finalized["holdback_cents"] == 914
    assert finalized["holdback_released_cents"] == 914
    assert finalized["holdback_forfeited_cents"] == 0
    assert finalized["offset_cents"] == 0
    assert finalized["net_payable_cents"] == 6962
    assert_vendor_money_invariant(finalized)


def test_each_deduction_line_is_rounded_before_the_lines_are_summed(api):
    """PRD 3.9: "Deductions come off gross, and **the rounding order here is pinned**: each
    deduction line is rounded to whole cents on its own, and only the already-rounded lines are
    summed. Summing the raw lines and rounding once at the end is wrong and produces a different
    total."
    PRD 3.9: "Worked through: for a net landing of 10.04 pounds, 12 offload minutes and a gross
    of 9136 cents, the raw lines are 800, 120.48, 1140 and 114.20; rounding each first gives 800
    plus 120 plus 1140 plus 114, which is 2174. Summing first would give 2174.68 and round to
    2175, and 2174 is the figure this system publishes."

    Design: Difficulty/combinatorial_formula/deduction_lines_rounded_before_summing
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = new_settlement(ctx["trip_id"], ctx["trip_version"])

    assert statement["dock_fee_cents"] == 800
    assert statement["ice_handling_cents"] == 120
    assert statement["offload_labor_cents"] == 1140
    assert statement["handling_levy_cents"] == 114
    assert statement["deductions_cents"] == 2174
    assert statement["deductions_cents"] != 2175


def test_gross_pay_is_the_ex_vessel_line_plus_the_banded_premium(api):
    """PRD 3.9: "The `ex_vessel_cents` is the lot's `ex_vessel_price_cents_per_lb` multiplied by
    its `landed_pounds_net`, rounded half up once on its own."
    PRD 3.9: "The three bracket amounts are summed exactly, without rounding, and the raw sum is
    then multiplied by the trip's band factor: `BAND_PREMIUM_FACTOR` pays 1.00 for `GREEN`, 0.85
    for `YELLOW`, 0.50 for `ORANGE` and 0.00 for `RED`. Only that final product is rounded, half
    up, once."
    PRD 3.9: "The `gross_cents` is `ex_vessel_cents` plus `premium_cents`."

    Design: Difficulty/combinatorial_formula/deduction_lines_rounded_before_summing
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = new_settlement(ctx["trip_id"], ctx["trip_version"])

    assert statement["ex_vessel_cents"] == 8534
    assert statement["premium_cents"] == 602
    assert statement["gross_cents"] == 9136
    assert statement["deductions_cents"] == (
        statement["dock_fee_cents"]
        + statement["ice_handling_cents"]
        + statement["offload_labor_cents"]
        + statement["handling_levy_cents"]
    )


def _discounted_lot_with_held_statement():
    """A PROVISIONAL statement whose lot is put on HOLD by a breach and then discounted."""
    ctx = setup_verified_cod_landing(10.04)
    ctx["statement"] = new_settlement(ctx["trip_id"], ctx["trip_version"])
    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 25, 9.0)
    disposition_lot(ctx["lot_id"], "DISCOUNT", officer_user_id="qo-1")
    return ctx


def test_a_discount_disposition_splits_the_holdback_in_half_at_finalization(api):
    """PRD 3.9: "When the lot is `DISCOUNTED`, `VENDOR_DISCOUNT_HOLDBACK_RELEASE_PCT` is 0.50,
    so `holdback_released_cents` is half the holdback rounded half up, `holdback_forfeited_cents`
    is whatever is left of the holdback after that release, and `offset_cents` is 0."
    PRD 3.9: "Finalized against a `DISCOUNTED` lot, 457 is released, 457 is forfeited, and the
    payable is 6505."

    Design: Difficulty/compensating_invariant/holdback_resolution_conserves_gross_settlement_cents
    """
    ctx = _discounted_lot_with_held_statement()
    assert read_lot(ctx["lot_id"])["quality_status"] == "DISCOUNTED"

    finalized = finalize_settlement(ctx["statement"]["id"])
    assert finalized["status"] == "FINAL"
    assert finalized["variant"] == "FINAL"
    assert finalized["holdback_cents"] == 914
    assert finalized["holdback_released_cents"] == 457
    assert finalized["holdback_forfeited_cents"] == 457
    assert finalized["offset_cents"] == 0
    assert finalized["net_payable_cents"] == 6505


def test_the_discount_finalization_conserves_every_gross_cent(api):
    """PRD 2.9: "`INV_VENDOR_MONEY` — on every statement that has reached `FINAL`, `gross_cents`
    equals `deductions_cents` plus `net_payable_cents` plus `holdback_forfeited_cents` plus
    `offset_cents`. Finalization resolves the holdback that statement creation withheld, and
    `holdback_released_cents` plus `holdback_forfeited_cents` always equals `holdback_cents`."
    PRD 3.9: "On every final split, `net_payable_cents` is `gross_cents` less `deductions_cents`
    less `holdback_forfeited_cents` less `offset_cents`."

    Design: Difficulty/compensating_invariant/holdback_resolution_conserves_gross_settlement_cents
    """
    ctx = _discounted_lot_with_held_statement()
    finalized = finalize_settlement(ctx["statement"]["id"])

    assert finalized["gross_cents"] == 9136
    assert finalized["deductions_cents"] == 2174
    assert_vendor_money_invariant(finalized)
    assert (
        finalized["gross_cents"]
        - finalized["deductions_cents"]
        - finalized["holdback_forfeited_cents"]
        - finalized["offset_cents"]
        == finalized["net_payable_cents"]
    )


def test_finalizing_while_the_lot_is_still_on_hold_is_refused(api):
    """PRD 3.9: "and a statement whose lot is still on `HOLD` cannot be finalized at all, being
    refused with `ERR_HOLDBACK_NOT_CLEARED`."
    PRD 3.6: "On the vendor side, any settlement statement of that lot standing in `PROVISIONAL`
    moves to `HELD`, and finalizing a held statement is refused with `ERR_HOLDBACK_NOT_CLEARED`
    for as long as the lot remains on hold."

    Design: Corner/validations/finalize_while_the_lot_is_on_hold_returns_holdback_not_cleared
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = new_settlement(ctx["trip_id"], ctx["trip_version"])
    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 25, 8.0)

    response = api.finalize_settlement(statement["id"], ADMIN)
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_HOLDBACK_NOT_CLEARED.value)

    held = read_settlement(statement["id"])
    assert held["status"] == "HELD"
    assert held["variant"] == "PROVISIONAL"
    assert held["net_payable_cents"] == 6048
    assert held["holdback_released_cents"] == 0
    assert held["holdback_forfeited_cents"] == 0


def test_paying_a_final_statement_disburses_its_net_payable(api):
    """PRD 3.9: "Payment is the last act: it moves the statement `FINAL → PAID` and sets
    `net_paid_cents` equal to `net_payable_cents`."

    Design: Corner/endpoints/settlement_pay_disburses_the_final_net_payable
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = new_settlement(ctx["trip_id"], ctx["trip_version"])
    finalize_settlement(statement["id"])

    paid = validate_success(api.pay_settlement(statement["id"], ADMIN))
    assert paid["status"] == "PAID"
    assert paid["net_paid_cents"] == 6962
    assert paid["net_payable_cents"] == 6962
    assert paid["gross_cents"] == 9136
    assert paid["deductions_cents"] == 2174
    assert paid["holdback_forfeited_cents"] == 0
    assert paid["offset_cents"] == 0
    assert_vendor_money_invariant(paid)


def test_a_restatement_carrying_the_pre_statement_trip_version_is_refused(api):
    """PRD 2.7: "The third is the vendor settlement. A request that creates a settlement
    statement for a trip must carry `expected_trip_version` equal to that trip's current
    `version`."
    PRD 3.9: "Creating a statement voids any earlier statement of the same trip standing in
    `DRAFT` or `PROVISIONAL`, moving it to `VOID`, and increments the trip's `version` by 1 —
    which is why a restatement needs a fresh read of the trip."

    Design: Corner/cross_cutting_complexity_layers/stale_trip_version_on_settlement_create_returns_412
    """
    ctx = setup_verified_cod_landing(10.04)
    statement = new_settlement(ctx["trip_id"], ctx["trip_version"])

    response = api.create_settlement(
        ctx["trip_id"], {"expected_trip_version": ctx["trip_version"]}, ADMIN
    )
    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    surviving = read_settlement(statement["id"])
    assert surviving["status"] == "PROVISIONAL"
    assert surviving["net_payable_cents"] == 6048

    _, meta = validate_paginated(api.list_settlements(ADMIN, {"trip_id": ctx["trip_id"]}))
    assert meta["total_count"] == 1


def test_a_recall_walks_the_lot_forward_to_every_box_it_reached(api):
    """PRD 3.9: "Hop one moves the lot to `RECALLED`. Hop two, caused by hop one, moves every
    sub-lot of that lot standing in `IN_TRANSIT` or `ARRIVED` to `RETURNED`."
    PRD 3.9: "Hop three, caused by hop two, reaches the boxes: every delivery carried by one of
    those sub-lots is visited in `created_at` ascending order, and for each the credit issued is
    its `invoice_total_cents` less whatever `credit_cents` it has already received. A delivery
    that had already reached `DELIVERED` or `PICKED_UP` has its money axis moved to `CREDITED`,
    whether it was standing in `CHARGED` or in `PARTIALLY_CREDITED`; a delivery that had not yet
    reached the member instead has its `fulfillment_status` moved to `VOIDED` with `fill_status`
    `VOID`."
    PRD 3.9: "Hop four, caused by hop three, records the damage: each credit is added to the
    delivery's `credit_cents` and to the owning member's `credit_balance_cents`, and the notice
    records `impacted_sub_lot_count` (the number of sub-lots walked), `impacted_delivery_count`
    (the number of deliveries reached through them), `impacted_member_count` (the number of
    *distinct* members behind those deliveries) and `total_credit_cents` (the sum of the credits
    issued during the walk)."

    The consignment still carries one box that has not reached its member, so it is beyond
    question still standing in `ARRIVED` when the recall reaches it.

    Design: Corner/state_machines/recall_notice_walks_forward_and_credits_the_delivered_box
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    collector = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        paid_cents=90000,
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    absentee = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Nils Two",
        email="m2@csf.test",
        paid_cents=90000,
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 10.00)
    allocate(landing["lot_id"], 1, landing["lot"]["version"])
    split_lot(landing["lot_id"], [hub_destination(hub["id"], 10.00)])
    sub_lot = sub_lots_of(landing["lot_id"])[0]
    arrive_sub_lot(sub_lot["id"])

    collected_box = delivery_of_week(collector["subscription_id"], 1)
    waiting_box = delivery_of_week(absentee["subscription_id"], 1)
    pack_delivery(collected_box["id"])
    pack_delivery(waiting_box["id"])

    window = new_window(hub["id"], ctx["season_id"], 1, cooler_slots_total=4)
    stage_delivery(collected_box["id"], window["id"])
    stage_delivery(waiting_box["id"], window["id"])
    set_clock("2026-05-04T13:00:00Z")
    open_window(window["id"])
    log_leg(landing["lot_id"], "HUB_HOLD", 0, 2.0)
    pickup_delivery(collected_box["id"], collector["member_id"])

    notice = new_recall(landing["lot_id"], "PATHOGEN")
    assert notice["status"] == "SCOPED"
    assert notice["impacted_sub_lot_count"] == 1
    assert notice["impacted_delivery_count"] == 2
    assert notice["impacted_member_count"] == 2
    assert notice["total_credit_cents"] == 9000

    assert read_lot(landing["lot_id"])["status"] == "RECALLED"
    assert read_sub_lot(sub_lot["id"])["status"] == "RETURNED"

    collected = read_delivery(collected_box["id"])
    assert collected["fulfillment_status"] == "PICKED_UP"
    assert collected["billing_status"] == "CREDITED"
    assert collected["credit_cents"] == 4500

    waiting = read_delivery(waiting_box["id"])
    assert waiting["fulfillment_status"] == "VOIDED"
    assert waiting["fill_status"] == "VOID"
    assert waiting["credit_cents"] == 4500

    assert read_member(collector["member_id"])["credit_balance_cents"] == 4500
    assert read_member(absentee["member_id"])["credit_balance_cents"] == 4500
    assert read_recall(notice["id"])["landing_lot_id"] == landing["lot_id"]


def test_opening_an_already_open_season_is_refused(api):
    """PRD 2.5: "The season is in the status the operation requires — otherwise
    `ERR_SEASON_NOT_OPEN` (HTTP 409)."
    PRD 2.5: "and opening the season requires it to be `PLANNING`."
    PRD 3.1: "Opening it — the `PLANNING → OPEN` move, available to an administrator — requires
    that the season currently be in `PLANNING` and that at least one share plan already exist
    for it"

    Design: Corner/state_machines/season_open_twice_is_rejected_as_invalid_state
    """
    ctx = setup_open_season(offered_species=("COD",))

    response = api.open_season(ctx["season_id"], ADMIN)
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_OPEN.value)
    assert read_season(ctx["season_id"])["status"] == "OPEN"


def _closed_season_after_true_up():
    """A season taken through OPEN, LANDINGS_CLOSED and the true-up sweep, with one
    installment subscription that was promised exactly the week-20 box."""
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    ctx.update(
        setup_member_subscription(
            ctx["season_id"],
            ctx["plan"]["id"],
            join_week_index=20,
            fulfillment_mode="HUB_PICKUP",
            pickup_hub_id=hub["id"],
        )
    )
    close_landings(ctx["season_id"])
    return ctx


def test_the_true_up_credits_an_installment_subscription_and_closes_the_season(api):
    """PRD 3.9: "`undelivered_count` is `promised_delivery_count` less `delivered_count`, less
    `credited_count`, less `member_fault_count`, less `skip_credited_count` — the promised boxes
    that reached season close in no other bucket at all."
    PRD 3.9: "Everything else takes the credit variant — an `INSTALLMENT` subscription always,
    and a prepaid subscription whose base owed is strictly below 5000 cents. On the credit
    variant no cash moves at all: `true_up_status` becomes `CREDITED`, `true_up_amount_cents` is
    the base owed, and the same figure is written to `rollover_credit_cents` for the member to
    carry into next season, which is what a renewing subscription picks up when it names a
    `renewed_from_subscription_id`."
    PRD 3.9: "Once every processed subscription carries a `true_up_status` of `REFUNDED` or
    `CREDITED`, each moves its `lifecycle_status` to `COMPLETED` and its `billing_status` to
    `SETTLED`"
    PRD 3.9: "The season's `true_up_run_at` is stamped from the logical clock and its `status`
    becomes `CLOSED`."

    Design: Corner/calculations/season_true_up_installment_branch_writes_rollover_credit
    """
    ctx = _closed_season_after_true_up()
    season = run_true_up(ctx["season_id"])

    assert season["status"] == "CLOSED"
    assert_same_instant(season["true_up_run_at"], "2026-05-01T00:00:00.000Z", "true_up_run_at")

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["promised_delivery_count"] == 1
    assert subscription["undelivered_count"] == 1
    assert subscription["true_up_status"] == "CREDITED"
    assert subscription["true_up_amount_cents"] == 4500
    assert subscription["rollover_credit_cents"] == 4500
    assert subscription["expired_credit_cents"] == 0
    assert subscription["lifecycle_status"] == "COMPLETED"
    assert subscription["billing_status"] == "SETTLED"


def test_a_closed_season_refuses_any_further_write_on_its_resources(api):
    """PRD 3.9: "From that moment no further mutation is accepted on any resource belonging to
    that season, and an attempt is refused with `ERR_SEASON_CLOSED` — with only the four
    carve-outs listed in §2.5 remaining open."
    PRD 2.5: "The season behind the addressed resource is not `CLOSED` — otherwise
    `ERR_SEASON_CLOSED` (HTTP 409)."

    Design: Corner/errors/error_season_closed_blocks_writes_after_true_up
    """
    ctx = _closed_season_after_true_up()
    run_true_up(ctx["season_id"])

    response = api.pause_subscription(
        ctx["subscription_id"], make_member_headers(ctx["member_id"])
    )
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SEASON_CLOSED.value)

    assert read_season(ctx["season_id"])["status"] == "CLOSED"
    assert read_subscription(ctx["subscription_id"])["lifecycle_status"] == "COMPLETED"
