"""Conserved quantities and the compensating moves that are meant to reverse them.

PRD.md section 2.10 declares two ledgers - resin mass in kilograms at three
decimals and warranty money in integer cents - and PRD.md section 3.7 defines a
third conserved aggregate, a site's committed cube in cubic metres at four
decimals. Their compensating moves differ in kind, which is what this module
pins:

* resin is partially reversible - a release returns the reservation exactly, but
  once the oven has started nothing comes back;
* warranty money is exactly reversible - a void moves the identical integer back
  and keeps the claim's money fields as the audit record;
* committed cube is reversible but asymmetric - releasing a nest anchor promotes
  a sibling, so the site falls by less than the released hull's own footprint.

In every case the invariant itself holds at every checkpoint; only the shape of
the reversal changes.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    abort_payload,
    api_client,
    approve_claim_payload,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_money_equals,
    assert_resin_ledger_conserved,
    assert_warranty_reserve_conserved,
    get_success_data,
    product_model_version,
    release_charge_payload,
    release_storage_payload,
    reserve_charge,
    run_cycle_to_oven_running,
    schedule_cycle,
    set_clock,
    setup_scheduled_cycle,
    setup_sellable_units,
    setup_submitted_claim,
    storage_review_payload,
    store_unit,
    validate_error,
    void_claim_payload,
)

# A lot holding exactly two full shots, so the second reservation drains it to
# exactly 0.000 rather than merely close to it.
_P2_TWO_SHOT_PLANT = {
    "model_overrides": {"nominal_charge_kg": 24.0},
    "mold_overrides": {"cavity_count": 1},
    "order_overrides": {"ordered_qty": 2},
    "lot_overrides": {"received_kg": 48.0},
}

# One cycle mints three sibling hulls of a model whose nested follower costs
# 1.0000 cube against a full 2.0000, so the anchor promotion delta is 1.0000.
_P2_THREE_SIBLINGS = {
    "model_overrides": {"nominal_charge_kg": 8.0},
    "mold_overrides": {"cavity_count": 3},
    "order_overrides": {"ordered_qty": 3},
}

_P2_SECOND_WINDOW = "2026-08-01T12:00:00Z"

# Exactly six complete calendar months after the delivery instant the shipment
# fixture stamps, so the frozen age is 6 and PRO_RATA_AGE covers 90.00 percent.
_P2_SIX_MONTHS_AFTER_DELIVERY = "2027-02-02T00:00:00Z"


def _p2_two_cycles_on_a_two_shot_lot() -> dict:
    """One order, two SCHEDULED cycles on disjoint windows, one 48.000 kg lot."""
    ctx = setup_scheduled_cycle(charge=False, **_P2_TWO_SHOT_PLANT)
    ctx["second_cycle"] = schedule_cycle(
        ctx, ctx["production_order"], oven_start_at=_P2_SECOND_WINDOW
    )
    return ctx


def _p2_lot(ctx: dict) -> dict:
    """Re-read the lot as the ResinTechnician who owns its ledger."""
    return api_client.read_entity(
        "get_resin_lot", ctx["resin_lot_id"], ctx["resin_tech_headers"]
    )


def _p2_assert_mass_ledger(
    lot: dict, available: str, reserved: str, consumed: str
) -> None:
    """Assert the three buckets and re-check the conservation identity."""
    assert_decimal_equals(lot["available_kg"], Decimal(available), Q_MASS, "available_kg")
    assert_decimal_equals(lot["reserved_kg"], Decimal(reserved), Q_MASS, "reserved_kg")
    assert_decimal_equals(lot["consumed_kg"], Decimal(consumed), Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(lot)


def _p2_claim_priced_at_six_months() -> dict:
    """A claim under review with a verified storage axis and a frozen age of 6.

    The claim ladder's own fixtures freeze the age at 0 months, so the review is
    started here by hand after the clock has moved, which is the only way to
    reach a coverage share other than 100.00 percent.
    """
    ctx = setup_submitted_claim()
    set_clock(_P2_SIX_MONTHS_AFTER_DELIVERY)
    ctx["warranty_claim"] = get_success_data(
        api_client.start_claim_review(ctx["warranty_claim_id"], ctx["agent_headers"])
    )
    ctx["warranty_claim"] = get_success_data(
        api_client.submit_storage_review(
            ctx["warranty_claim_id"],
            storage_review_payload("VERIFIED"),
            ctx["agent_headers"],
        )
    )
    return ctx


def _p2_approve(ctx: dict) -> dict:
    """Approve the claim against a freshly read model version."""
    return get_success_data(
        api_client.approve_warranty_claim(
            ctx["warranty_claim_id"],
            approve_claim_payload(product_model_version(ctx["product_model_id"])),
            ctx["agent_headers"],
        )
    )


def _p2_model(ctx: dict) -> dict:
    """Re-read the hull model that holds the warranty reserve ledger."""
    return api_client.read_entity(
        "get_product_model", ctx["product_model_id"], ctx["admin_headers"]
    )


def _p2_summary(ctx: dict) -> dict:
    """Read the site's footprint summary as the LogisticsPlanner."""
    return api_client.read_footprint_summary(
        ctx["warehouse_id"], ctx["planner_headers"]
    )


def _p2_three_hulls_in_one_zone() -> dict:
    """Store three siblings at strictly increasing instants: anchor then two nested.

    Stepping the clock between the stores makes ``stored_at`` strictly increasing,
    which fixes the promotion target PRD.md section 3.7 orders by ascending
    ``stored_at``.
    """
    ctx = setup_sellable_units(**_P2_THREE_SIBLINGS)
    assert len(ctx["sellable_units"]) == 3
    stored = []
    for offset, unit in enumerate(ctx["sellable_units"]):
        set_clock(f"2026-08-01T11:{offset * 5:02d}:00Z")
        stored.append(store_unit(ctx, unit))
    ctx["stored_units"] = stored
    return ctx


def test_reserving_to_exactly_zero_depletes_the_lot_and_the_release_restores_it_exactly():
    """Two reservations drain the lot to 0.000, and one release gives it back.

    PRD.md section 2.10: "A resin lot holds a three-bucket ledger in which the
    rounded sum of `available_kg`, `reserved_kg` and `consumed_kg` always equals
    the immutable `received_kg`. Reserving mass moves it from available to
    reserved; consuming it at oven start moves it from reserved to consumed;
    releasing a still-reserved charge moves it back from reserved to available."

    PRD.md section 3.2 pins the equality that makes the second reservation legal
    and the depletion exact: "the lot's `available_kg` must be at least
    `charge_kg`, equality being legal and draining the lot to exactly 0.000",
    and "a lot whose `available_kg` reaches exactly 0.000 moves `AVAILABLE` to
    `DEPLETED`".

    PRD.md section 3.2 then fixes the compensating move: "The optional
    `release_reason` supplies `released_reason`; when it is omitted,
    `released_reason` is set to `CYCLE_ABORTED`. On release `charge_kg` moves from
    the lot's `reserved_kg` back to its `available_kg`, a `DEPLETED` lot that
    regains mass returns to `AVAILABLE`".

    Design: Difficulty/compensating_invariant/resin_mass_ledger_conserved_across_reserve_release_and_irreversible_consume
    """
    ctx = _p2_two_cycles_on_a_two_shot_lot()

    first_charge = reserve_charge(ctx, ctx["molding_cycle"], ctx["resin_lot"])
    assert_decimal_equals(first_charge["virgin_kg"], Decimal("21.600"), Q_MASS, "virgin_kg")
    assert_decimal_equals(
        first_charge["charge_regrind_pct"], Decimal("10.00"), Q_PERCENT, "charge_regrind_pct"
    )
    _p2_assert_mass_ledger(_p2_lot(ctx), "24.000", "24.000", "0.000")

    second_charge = reserve_charge(ctx, ctx["second_cycle"], ctx["resin_lot"])
    drained = _p2_lot(ctx)
    _p2_assert_mass_ledger(drained, "0.000", "48.000", "0.000")
    assert drained["status"] == "DEPLETED"

    released = get_success_data(
        api_client.release_resin_charge(
            second_charge["id"], release_charge_payload(), ctx["resin_tech_headers"]
        )
    )
    assert released["status"] == "RELEASED"
    assert released["released_reason"] == "CYCLE_ABORTED"

    restored = _p2_lot(ctx)
    _p2_assert_mass_ledger(restored, "24.000", "24.000", "0.000")
    assert restored["status"] == "AVAILABLE"

    # A RELEASED charge drops out of the roll-ups the instant it is released.
    emptied = api_client.read_entity(
        "get_molding_cycle", ctx["second_cycle"]["id"], ctx["operator_headers"]
    )
    assert_decimal_equals(
        emptied["charged_mass_kg"], Decimal("0.000"), Q_MASS, "charged_mass_kg"
    )
    assert emptied["weighted_melt_index_g10min"] is None


def test_start_oven_moves_reserved_mass_to_consumed_without_creating_or_destroying_mass():
    """Consumption is a transfer between buckets, not a new quantity.

    PRD.md section 3.5: "Every `RESERVED` charge on the cycle becomes `CONSUMED`,
    moving `charge_kg` from its lot's `reserved_kg` to its lot's `consumed_kg`
    while `available_kg` is untouched".

    PRD.md section 2.10 keeps the identity in force across that move: the rounded
    sum of the three buckets "always equals the immutable `received_kg`".

    Design: Difficulty/compensating_invariant/resin_mass_ledger_conserved_across_reserve_release_and_irreversible_consume
    """
    ctx = _p2_two_cycles_on_a_two_shot_lot()
    charge = reserve_charge(ctx, ctx["molding_cycle"], ctx["resin_lot"])
    _p2_assert_mass_ledger(_p2_lot(ctx), "24.000", "24.000", "0.000")

    run_cycle_to_oven_running(ctx)
    assert ctx["molding_cycle"]["status"] == "OVEN_RUNNING"

    consumed = _p2_lot(ctx)
    _p2_assert_mass_ledger(consumed, "24.000", "0.000", "24.000")
    assert consumed["status"] == "AVAILABLE"

    charge_row = api_client.read_entity(
        "get_resin_charge", charge["id"], ctx["resin_tech_headers"]
    )
    assert charge_row["status"] == "CONSUMED"
    assert_decimal_equals(charge_row["charge_kg"], Decimal("24.000"), Q_MASS, "charge_kg")


def test_aborting_from_oven_running_leaves_the_consumed_mass_on_the_lot():
    """The compensating move is unavailable once the shot has been consumed.

    PRD.md section 3.5: "Aborting from `OVEN_RUNNING` or from `COOLING` returns the
    tool `IN_CYCLE` to `AVAILABLE` *without* incrementing `cycles_since_service`,
    but charges already `CONSUMED` are **not** restored: `consumed_kg` stays on the
    lot as a scrapped shot, `available_kg` does not rise, and consequently no order
    is unblocked."

    PRD.md section 2.10 states the same asymmetry as a property of the ledger:
    "Consumption is irreversible - `consumed_kg` is never decremented - which is
    why an abort after the oven has started returns no resin." The invariant still
    holds; only the reversal is missing.

    PRD.md section 3.2 confirms the charge itself is now frozen: "a `CONSUMED`
    charge can never be released, because consumption is irreversible."

    Design: Difficulty/compensating_invariant/resin_mass_ledger_conserved_across_reserve_release_and_irreversible_consume
    """
    ctx = _p2_two_cycles_on_a_two_shot_lot()
    charge = reserve_charge(ctx, ctx["molding_cycle"], ctx["resin_lot"])
    run_cycle_to_oven_running(ctx)
    before = _p2_lot(ctx)
    _p2_assert_mass_ledger(before, "24.000", "0.000", "24.000")

    aborted = get_success_data(
        api_client.abort_molding_cycle(
            ctx["molding_cycle_id"], abort_payload(), ctx["operator_headers"]
        )
    )
    assert aborted["status"] == "ABORTED"

    after = _p2_lot(ctx)
    _p2_assert_mass_ledger(after, "24.000", "0.000", "24.000")
    assert after["status"] == "AVAILABLE"
    assert after["version"] == before["version"], (
        "an abort that returns no resin must not touch the lot"
    )

    charge_row = api_client.read_entity(
        "get_resin_charge", charge["id"], ctx["resin_tech_headers"]
    )
    assert charge_row["status"] == "CONSUMED"
    validate_error(
        api_client.release_resin_charge(
            charge["id"], release_charge_payload(), ctx["resin_tech_headers"]
        ),
        ApiErrorId.CHARGE_NOT_RELEASABLE,
        409,
    )

    # The abort touched only its own cycle's rows.
    untouched = api_client.read_entity(
        "get_molding_cycle", ctx["second_cycle"]["id"], ctx["operator_headers"]
    )
    assert untouched["status"] == "SCHEDULED"
    assert_decimal_equals(
        untouched["charged_mass_kg"], Decimal("0.000"), Q_MASS, "charged_mass_kg"
    )


def test_approving_a_claim_moves_the_identical_integer_between_the_two_reserve_buckets():
    """The reserve falls by exactly the net payout and the paid bucket rises by it.

    PRD.md section 3.9 prices the claim in a fixed order: under "the `PRO_RATA_AGE`
    variant the coverage percentage is 60 minus `months_in_service`, divided by 60,
    times 100, rounded to two decimals"; "`pre_fee_gross_cents` is the model's
    `msrp_cents` multiplied by the coverage percentage divided by 100, multiplied by
    the claim-type factor - 1.00 for `HULL_DEFORMATION` ... - and rounded half-up to
    whole cents"; "`admin_fee_cents` is the gross multiplied by the rate of the
    **first** tier whose maximum gross is at or above `pre_fee_gross_cents`, from an
    ordered ladder of 50000 cents at 12.00 percent and 200000 cents at 8.00
    percent"; "`storage_deduction_cents` is ... exactly 0 when it is
    `GUIDANCE_VERIFIED`"; and "`net_payout_cents` is the gross minus the deduction
    minus the fee, floored at 0".

    PRD.md section 3.9 then moves the ledger: "the model's `warranty_reserve_cents`
    decreases by `net_payout_cents` and its `warranty_paid_cents` increases by the
    identical integer. No rounding happens in the ledger itself, because the amount
    was already rounded during pricing. The invariant `warranty_reserve_cents` plus
    `warranty_paid_cents` equals `initial_warranty_reserve_cents` holds after every
    ledger move, without exception."

    Design: Difficulty/compensating_invariant/warranty_reserve_ledger_conserved_across_approve_and_void
    """
    ctx = _p2_claim_priced_at_six_months()
    assert ctx["warranty_claim"]["months_in_service"] == 6
    assert ctx["warranty_claim"]["storage_review_status"] == "GUIDANCE_VERIFIED"

    before = _p2_model(ctx)
    assert_money_equals(before["warranty_reserve_cents"], 500000, "warranty_reserve_cents")
    assert_money_equals(before["warranty_paid_cents"], 0, "warranty_paid_cents")
    assert_warranty_reserve_conserved(before)

    approved = _p2_approve(ctx)
    assert approved["claim_status"] == "APPROVED"
    assert approved["payout_basis"] == "PRO_RATA_AGE"
    assert_money_equals(approved["pre_fee_gross_cents"], 162000, "pre_fee_gross_cents")
    assert_money_equals(approved["admin_fee_cents"], 12960, "admin_fee_cents")
    assert_money_equals(
        approved["storage_deduction_cents"], 0, "storage_deduction_cents"
    )
    assert_money_equals(approved["net_payout_cents"], 149040, "net_payout_cents")

    after = _p2_model(ctx)
    assert_money_equals(after["warranty_reserve_cents"], 350960, "warranty_reserve_cents")
    assert_money_equals(after["warranty_paid_cents"], 149040, "warranty_paid_cents")
    assert_warranty_reserve_conserved(after)
    assert after["version"] == before["version"] + 1


def test_voiding_an_approved_claim_restores_the_reserve_exactly_and_retains_the_money_fields():
    """The void is an exact reversal that keeps the audit record intact.

    PRD.md section 3.9: "**Voiding** an approved claim is a `PlantAdmin` action
    carrying a `void_reason`. It moves `claim_status` `APPROVED` to `VOIDED`, sets
    `denial_reason` to `APPROVAL_VOIDED`, and reverses the ledger exactly: the
    model's `warranty_reserve_cents` increases and its `warranty_paid_cents`
    decreases by the claim's recorded `net_payout_cents`, restoring the conserved
    sum. This is the **only** path in the system that raises a reserve. Unlike
    denial, voiding **retains** the claim's money fields as the audit record; they
    are not zeroed. Both versions advance by 1."

    PRD.md section 2.10 states the same identity the reversal restores: a hull model
    holds "a two-bucket ledger in which `warranty_reserve_cents` plus
    `warranty_paid_cents` always equals the immutable
    `initial_warranty_reserve_cents`; approving a claim moves the net payout from
    reserve to paid, and voiding an approval moves the identical integer back."

    Design: Difficulty/compensating_invariant/warranty_reserve_ledger_conserved_across_approve_and_void
    """
    ctx = _p2_claim_priced_at_six_months()
    approved = _p2_approve(ctx)
    drawn = _p2_model(ctx)
    assert_money_equals(drawn["warranty_reserve_cents"], 350960, "warranty_reserve_cents")

    voided = get_success_data(
        api_client.void_warranty_claim(
            ctx["warranty_claim_id"], void_claim_payload(), ctx["admin_headers"]
        )
    )
    assert voided["claim_status"] == "VOIDED"
    assert voided["denial_reason"] == "APPROVAL_VOIDED"

    # Retained, not zeroed: the reversal stays reproducible from the claim row.
    assert_money_equals(voided["net_payout_cents"], 149040, "net_payout_cents")
    assert_money_equals(voided["pre_fee_gross_cents"], 162000, "pre_fee_gross_cents")
    assert_money_equals(voided["admin_fee_cents"], 12960, "admin_fee_cents")
    assert_money_equals(voided["storage_deduction_cents"], 0, "storage_deduction_cents")
    assert voided["payout_basis"] == approved["payout_basis"]
    assert voided["version"] == approved["version"] + 1

    restored = _p2_model(ctx)
    assert_money_equals(
        restored["warranty_reserve_cents"], 500000, "warranty_reserve_cents"
    )
    assert_money_equals(restored["warranty_paid_cents"], 0, "warranty_paid_cents")
    assert_warranty_reserve_conserved(restored)
    assert restored["version"] == drawn["version"] + 1


def test_nested_stores_accumulate_the_committed_cube_at_four_decimals():
    """One anchor plus two followers commit 2.0000 + 1.0000 + 1.0000 cube.

    PRD.md section 3.7: "the candidate footprint is the model's `gross_cube_m3`
    multiplied by its `nest_factor` and rounded to four decimals when an anchor
    exists, and simply `gross_cube_m3` rounded to four decimals when none does;
    the zone's committed cube is the rounded sum of `stored_footprint_cube_m3` over
    its occupying hulls".

    PRD.md section 3.7 also splits the two variants by cost: "Opening a **new nest
    group** - no eligible zone anchors this model - charges the full
    `gross_cube_m3` and sets `is_zone_anchor` true. **Joining an existing nest
    group** charges `gross_cube_m3` multiplied by `nest_factor` and leaves
    `is_zone_anchor` false".

    PRD.md section 2.10 makes the site total a pure aggregate: "a warehouse's
    `committed_cube_m3` is always the rounded sum of `stored_footprint_cube_m3` over
    its units in `logistics_status` `STORED` or `LOADED`".

    Design: Difficulty/compensating_invariant/storage_footprint_conserved_with_asymmetric_anchor_promotion
    """
    ctx = _p2_three_hulls_in_one_zone()
    anchor, second, third = ctx["stored_units"]

    assert_decimal_equals(
        anchor["stored_footprint_cube_m3"], Decimal("2.0000"), Q_CUBE, "anchor footprint"
    )
    assert anchor["is_zone_anchor"] is True
    assert anchor["storage_zone_code"] == "Z-A"

    for follower in (second, third):
        assert_decimal_equals(
            follower["stored_footprint_cube_m3"],
            Decimal("1.0000"),
            Q_CUBE,
            "nested footprint",
        )
        assert follower["is_zone_anchor"] is False
        assert follower["storage_zone_code"] == "Z-A"

    site = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_decimal_equals(
        site["committed_cube_m3"], Decimal("4.0000"), Q_CUBE, "committed_cube_m3"
    )
    assert_decimal_equals(
        site["utilization_pct"], Decimal("20.00"), Q_PERCENT, "utilization_pct"
    )
    assert site["posture"] == "NORMAL"

    summary = _p2_summary(ctx)
    assert_decimal_equals(
        summary["remaining_cube_m3"], Decimal("16.0000"), Q_CUBE, "remaining_cube_m3"
    )
    assert_footprint_summary_consistent(summary)


def test_releasing_the_anchor_promotes_the_earliest_survivor_and_costs_less_than_it_freed():
    """Removing a 2.0000 cube anchor lowers the site by only 1.0000 cube.

    PRD.md section 3.7: "(2) when the released hull *was* its nest group's anchor
    and followers remain, the earliest surviving occupant of the same
    site-zone-model group - ordered by ascending `stored_at` with ascending
    `hull_serial` as the total tie-break - is promoted: its `is_zone_anchor` becomes
    true and its `stored_footprint_cube_m3` is re-charged to the full
    `gross_cube_m3` rounded to four decimals."

    PRD.md section 3.7 states the resulting asymmetry outright: "Promotion **raises**
    the group's total footprint by `gross_cube_m3` multiplied by one minus
    `nest_factor`, so releasing one hull can leave the site more utilised than a
    naive subtraction predicts."

    PRD.md section 3.7 also fixes what the released hull keeps: "(1) the hull moves
    `STORED` to `UNALLOCATED`, its `warehouse_id`, `storage_zone_code`, `stored_at`
    and `demand_bucket_id` are cleared, its `stored_footprint_cube_m3` is set to
    0.0000 and `is_zone_anchor` to false".

    Design: Difficulty/compensating_invariant/storage_footprint_conserved_with_asymmetric_anchor_promotion
    """
    ctx = _p2_three_hulls_in_one_zone()
    anchor, second, third = ctx["stored_units"]

    released = get_success_data(
        api_client.release_storage(
            anchor["id"],
            release_storage_payload(release_reason="Owner pickup at plant"),
            ctx["planner_headers"],
        )
    )
    assert released["logistics_status"] == "UNALLOCATED"
    assert released["is_zone_anchor"] is False
    assert released["storage_zone_code"] is None
    assert_decimal_equals(
        released["stored_footprint_cube_m3"],
        Decimal("0.0000"),
        Q_CUBE,
        "released footprint",
    )

    promoted = api_client.read_entity(
        "get_finished_unit", second["id"], ctx["planner_headers"]
    )
    assert promoted["is_zone_anchor"] is True
    assert_decimal_equals(
        promoted["stored_footprint_cube_m3"],
        Decimal("2.0000"),
        Q_CUBE,
        "promoted footprint",
    )

    untouched = api_client.read_entity(
        "get_finished_unit", third["id"], ctx["planner_headers"]
    )
    assert untouched["is_zone_anchor"] is False
    assert_decimal_equals(
        untouched["stored_footprint_cube_m3"],
        Decimal("1.0000"),
        Q_CUBE,
        "surviving follower footprint",
    )

    # 4.0000 - 2.0000 would predict 2.0000; the promotion adds 1.0000 back.
    site = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_decimal_equals(
        site["committed_cube_m3"], Decimal("3.0000"), Q_CUBE, "committed_cube_m3"
    )
    assert_decimal_equals(
        site["utilization_pct"], Decimal("15.00"), Q_PERCENT, "utilization_pct"
    )
    assert site["posture"] == "NORMAL"
    assert_footprint_summary_consistent(_p2_summary(ctx))


def test_the_re_stored_former_anchor_returns_as_a_follower_and_the_site_total_comes_back():
    """The site total returns to 4.0000 while the per-hull allocation stays swapped.

    PRD.md section 3.7: "an anchor exists when some occupying hull in that zone
    shares the candidate's `product_model_id` and carries `is_zone_anchor` true; the
    candidate footprint is the model's `gross_cube_m3` multiplied by its
    `nest_factor` and rounded to four decimals when an anchor exists". The promoted
    sibling now holds the anchor slot, so the returning hull pays the nested charge
    and the anchor role does not revert.

    PRD.md section 2.10 keeps the aggregate honest at every checkpoint: "a
    warehouse's `committed_cube_m3` is always the rounded sum of
    `stored_footprint_cube_m3` over its units in `logistics_status` `STORED` or
    `LOADED`", and "Nothing is cached across requests."

    Design: Difficulty/compensating_invariant/storage_footprint_conserved_with_asymmetric_anchor_promotion
    """
    ctx = _p2_three_hulls_in_one_zone()
    anchor, second, third = ctx["stored_units"]
    get_success_data(
        api_client.release_storage(
            anchor["id"],
            release_storage_payload(release_reason="Owner pickup at plant"),
            ctx["planner_headers"],
        )
    )

    set_clock("2026-08-01T11:15:00Z")
    returned = store_unit(ctx, anchor)
    assert returned["logistics_status"] == "STORED"
    assert returned["storage_zone_code"] == "Z-A"
    assert returned["is_zone_anchor"] is False
    assert_decimal_equals(
        returned["stored_footprint_cube_m3"],
        Decimal("1.0000"),
        Q_CUBE,
        "re-stored footprint",
    )

    # The allocation is the exact inverse of the opening one.
    still_anchor = api_client.read_entity(
        "get_finished_unit", second["id"], ctx["planner_headers"]
    )
    assert still_anchor["is_zone_anchor"] is True
    assert_decimal_equals(
        still_anchor["stored_footprint_cube_m3"],
        Decimal("2.0000"),
        Q_CUBE,
        "promoted footprint",
    )
    assert_decimal_equals(
        api_client.read_entity("get_finished_unit", third["id"], ctx["planner_headers"])[
            "stored_footprint_cube_m3"
        ],
        Decimal("1.0000"),
        Q_CUBE,
        "surviving follower footprint",
    )

    site = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_decimal_equals(
        site["committed_cube_m3"], Decimal("4.0000"), Q_CUBE, "committed_cube_m3"
    )
    assert_decimal_equals(
        site["utilization_pct"], Decimal("20.00"), Q_PERCENT, "utilization_pct"
    )
    assert site["posture"] == "NORMAL"

    summary = _p2_summary(ctx)
    assert_decimal_equals(
        summary["remaining_cube_m3"], Decimal("16.0000"), Q_CUBE, "remaining_cube_m3"
    )
    assert_footprint_summary_consistent(summary)
