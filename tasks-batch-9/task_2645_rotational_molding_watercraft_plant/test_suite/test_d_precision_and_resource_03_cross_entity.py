"""State that one entity owns but another entity's writes depend on.

Two dependencies run in opposite directions across the plant:

* upstream material — a ProductionOrder's schedulability depends on whether any
  ResinLot still qualifies for its model, so quarantining the only qualified lot
  closes the booking endpoint and releasing that quarantine reopens it (PRD.md
  sections 3.2 and 3.3);
* downstream capacity — a FinishedUnit's move to `STORED` depends on the target
  Warehouse's derived `posture`, so filling the site refuses the next store and
  releasing a sibling's storage admits it again (PRD.md sections 3.7 and 3.3).

Neither dependency is latched: both are re-derived on every write, which the
last test of each group asserts by driving the same gate twice.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    api_client,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_resin_ledger_conserved,
    get_success_data,
    molding_cycle_payload,
    production_order_version,
    quarantine_payload,
    release_quarantine_payload,
    release_storage_payload,
    set_clock,
    setup_scheduled_cycle,
    setup_sellable_units,
    store_payload,
    store_unit,
    validate_error,
    warehouse_version,
    zone,
)

# A second window well clear of the 09:00-10:30 window the fixture books, so no
# arm, bay or mould conflict can be mistaken for the order-status refusal.
_P2_SECOND_WINDOW = "2026-08-01T12:00:00Z"

# One anchor hull at 2.0000 cube plus one nested sibling at 1.0000 cube fill this
# site exactly, taking it from 66.67 percent to 100.00 percent.
_P2_TIGHT_SITE = {
    "footprint_capacity_cube_m3": 3.0,
    "zones": [zone("Z-A", 3.0)],
    "restricted_threshold_pct": 85.0,
    "frozen_threshold_pct": 95.0,
}

# Three hulls from one cycle against an ordered quantity of four: the order stays
# IN_PRODUCTION with `completed_qty` 3 below `ordered_qty` 4, so it remains a
# candidate for the storage cascade's blocking link instead of reaching COMPLETE.
_P2_THREE_CAVITY_TIGHT = {
    "model_overrides": {"nominal_charge_kg": 8.0},
    "mold_overrides": {"cavity_count": 3},
    "order_overrides": {"ordered_qty": 4},
    "warehouse_overrides": _P2_TIGHT_SITE,
}


def _p2_attempt_booking(ctx: dict, oven_start_at: str = _P2_SECOND_WINDOW):
    """POST one cycle on the context's station arm 1, returning the raw response."""
    return api_client.create_molding_cycle(
        molding_cycle_payload(
            ctx["production_order_id"],
            ctx["oven_station_id"],
            ctx["cooling_bay_id"],
            production_order_version(ctx["production_order_id"]),
            oven_start_at=oven_start_at,
        ),
        ctx["operator_headers"],
    )


def _p2_quarantine_only_lot(ctx: dict) -> dict:
    """Quarantine the single qualified lot as the QualityInspector who owns it."""
    return get_success_data(
        api_client.quarantine_resin_lot(
            ctx["resin_lot_id"],
            quarantine_payload(quarantine_reason="Colour drift audit"),
            ctx["inspector_headers"],
        )
    )


def _p2_three_sellable_hulls() -> dict:
    """Three SELLABLE hulls of one model and a site only two of them fit."""
    ctx = setup_sellable_units(**_P2_THREE_CAVITY_TIGHT)
    assert len(ctx["sellable_units"]) == 3, "the three-cavity tool mints three hulls"
    set_clock("2026-08-01T11:00:00Z")
    return ctx


def _p2_fill_the_site(ctx: dict) -> tuple[dict, dict]:
    """Store the first two hulls, which lands the site on exactly 100.00 percent."""
    first = store_unit(ctx, ctx["sellable_units"][0])
    second = store_unit(ctx, ctx["sellable_units"][1])
    return first, second


def _p2_summary(ctx: dict) -> dict:
    """Read the target site's footprint summary as the LogisticsPlanner."""
    return api_client.read_footprint_summary(
        ctx["warehouse_id"], ctx["planner_headers"]
    )


def test_quarantining_the_only_qualified_lot_blocks_the_order_and_its_next_cycle():
    """The order's schedulability collapses when its last lot leaves AVAILABLE.

    PRD.md section 3.2: "`QualityInspector` alone quarantines a lot, supplying a
    `quarantine_reason`, and quarantine is the head of **CASCADE-F**: (1) the lot
    moves `AVAILABLE` or `DEPLETED` to `QUARANTINED`; (2) every `RESERVED` charge
    drawn on that lot becomes `RELEASED` with `released_reason` `LOT_QUARANTINED`,
    moving `charge_kg` from `reserved_kg` back to `available_kg`; (3) every cycle
    in `SCHEDULED` that held one of those charges becomes `ABORTED` with
    `abort_reason` `LOT_QUARANTINED`; and (4) every affected order left with no
    remaining qualified lot moves to `BLOCKED_RESIN` with `blocked_reason`
    `NO_QUALIFIED_RESIN_LOT`. The lot's `version` advances by 1."

    PRD.md section 3.2 makes the collapse total: a lot qualifies only when "the
    lot's `status` is `AVAILABLE`, so `QUARANTINED`, `EXPIRED` and `DEPLETED`
    lots never qualify", and this plant holds exactly one lot.

    PRD.md section 3.4 then closes the booking endpoint: "The order's `status`
    must be `READY_TO_SCHEDULE` or `IN_PRODUCTION`; a `DRAFT`, `BLOCKED_RESIN`,
    `BLOCKED_WAREHOUSE`, `COMPLETE` or `CANCELLED` order cannot take a new cycle
    and is refused with `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/production_order_blocks_on_resin_lot_quarantine_and_unblocks_on_release
    """
    ctx = setup_scheduled_cycle()
    # The reservation already moved the lot on: PRD.md section 3.2 says of a
    # charge create that "both the lot's and the cycle's `version` advance by 1",
    # so the row the fixture captured at creation is a revision behind and the
    # baseline has to be re-read.
    lot_version_before = api_client.read_version(
        "get_resin_lot", ctx["resin_lot_id"], ctx["resin_tech_headers"]
    )
    order_before = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order_before["status"] == "IN_PRODUCTION"

    quarantined = _p2_quarantine_only_lot(ctx)
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["version"] == lot_version_before + 1

    charge = api_client.read_entity(
        "get_resin_charge", ctx["resin_charge_id"], ctx["resin_tech_headers"]
    )
    assert charge["status"] == "RELEASED"
    assert charge["released_reason"] == "LOT_QUARANTINED"

    cycle = api_client.read_entity(
        "get_molding_cycle", ctx["molding_cycle_id"], ctx["operator_headers"]
    )
    assert cycle["status"] == "ABORTED"
    assert cycle["abort_reason"] == "LOT_QUARANTINED"

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "BLOCKED_RESIN"
    assert order["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT"

    # Aborting from SCHEDULED returns the whole reservation to the lot.
    lot = api_client.read_entity(
        "get_resin_lot", ctx["resin_lot_id"], ctx["resin_tech_headers"]
    )
    assert_decimal_equals(lot["available_kg"], Decimal("500.000"), Q_MASS, "available_kg")
    assert_decimal_equals(lot["reserved_kg"], Decimal("0.000"), Q_MASS, "reserved_kg")
    assert_decimal_equals(lot["consumed_kg"], Decimal("0.000"), Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(lot)

    validate_error(
        _p2_attempt_booking(ctx),
        ApiErrorId.ORDER_NOT_SCHEDULABLE,
        409,
    )


def test_release_quarantine_returns_the_order_to_ready_and_admits_the_identical_booking():
    """Restoring the lot restores the order, and the refused POST now succeeds.

    PRD.md section 3.2: "Releasing a quarantine, also reserved to
    `QualityInspector`, carries a `release_note` and requires `status`
    `QUARANTINED`; the lot returns to `AVAILABLE` when `available_kg` is strictly
    greater than 0.000 and to `DEPLETED` otherwise. A return to `AVAILABLE`
    unblocks the `BLOCKED_RESIN` orders the lot qualifies for, again diverting to
    `BLOCKED_WAREHOUSE` where the target site is frozen."

    PRD.md section 3.3 names the destination exactly: "An order in `BLOCKED_RESIN`
    for which a qualified lot has returned to `AVAILABLE` moves to
    `READY_TO_SCHEDULE` with `blocked_reason` cleared **only if** the target
    site's `posture` is not `FROZEN`", and "Every one of these edges advances the
    order's `version` by 1." This site is empty and therefore NORMAL, so the order
    lands on `READY_TO_SCHEDULE`, and the booking PRD.md section 3.4 refused while
    it was `BLOCKED_RESIN` is admitted unchanged.

    Design: Difficulty/cross_entity_state_dependency/production_order_blocks_on_resin_lot_quarantine_and_unblocks_on_release
    """
    ctx = setup_scheduled_cycle()
    _p2_quarantine_only_lot(ctx)
    blocked = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert blocked["status"] == "BLOCKED_RESIN"

    released = get_success_data(
        api_client.release_resin_lot_quarantine(
            ctx["resin_lot_id"],
            release_quarantine_payload(),
            ctx["inspector_headers"],
        )
    )
    assert released["status"] == "AVAILABLE"

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "READY_TO_SCHEDULE"
    assert order["blocked_reason"] is None
    assert order["version"] == blocked["version"] + 1

    booked = get_success_data(_p2_attempt_booking(ctx))
    assert booked["status"] == "SCHEDULED"
    assert booked["mold_id"] == ctx["mold_id"]

    after = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert after["status"] == "IN_PRODUCTION"


def test_cycles_aborted_by_the_quarantine_are_not_resurrected_by_the_release():
    """The unblock edge restores the order, never the abandoned cycle.

    PRD.md section 3.2: "Cycles aborted by the quarantine are never resurrected."
    The same section fixes what the charge keeps: the released charge stays
    `RELEASED` with `released_reason` `LOT_QUARANTINED`, its mass already having
    moved "from `reserved_kg` back to `available_kg`", and releasing the
    quarantine performs no compensating re-reservation.

    Design: Difficulty/cross_entity_state_dependency/production_order_blocks_on_resin_lot_quarantine_and_unblocks_on_release
    """
    ctx = setup_scheduled_cycle()
    _p2_quarantine_only_lot(ctx)
    aborted = api_client.read_entity(
        "get_molding_cycle", ctx["molding_cycle_id"], ctx["operator_headers"]
    )
    assert aborted["status"] == "ABORTED"

    get_success_data(
        api_client.release_resin_lot_quarantine(
            ctx["resin_lot_id"],
            release_quarantine_payload(),
            ctx["inspector_headers"],
        )
    )

    cycle = api_client.read_entity(
        "get_molding_cycle", ctx["molding_cycle_id"], ctx["operator_headers"]
    )
    assert cycle["status"] == "ABORTED"
    assert cycle["abort_reason"] == "LOT_QUARANTINED"
    assert cycle["version"] == aborted["version"]

    charge = api_client.read_entity(
        "get_resin_charge", ctx["resin_charge_id"], ctx["resin_tech_headers"]
    )
    assert charge["status"] == "RELEASED"
    assert charge["released_reason"] == "LOT_QUARANTINED"

    lot = api_client.read_entity(
        "get_resin_lot", ctx["resin_lot_id"], ctx["resin_tech_headers"]
    )
    assert lot["status"] == "AVAILABLE"
    assert_decimal_equals(lot["available_kg"], Decimal("500.000"), Q_MASS, "available_kg")
    assert_decimal_equals(lot["reserved_kg"], Decimal("0.000"), Q_MASS, "reserved_kg")
    assert_resin_ledger_conserved(lot)


def test_second_store_freezes_the_site_and_the_third_store_is_refused_frozen():
    """Filling the site closes the store endpoint on the surviving sibling.

    PRD.md section 3.7 orders the gates: "Four gates apply in priority order.
    First, the site's `posture` must not be `FROZEN`, otherwise
    `ERR_WAREHOUSE_FROZEN` (HTTP 409). ... Fourth, the bucket's quota and then the
    site's total cube must both hold." The posture gate therefore answers before
    any cube arithmetic, so the third hull is refused `ERR_WAREHOUSE_FROZEN` and
    never `ERR_WAREHOUSE_CUBE_EXCEEDED`.

    PRD.md section 3.7 also fixes the two footprints and the admission of the
    second hull: "the candidate footprint is the model's `gross_cube_m3`
    multiplied by its `nest_factor` and rounded to four decimals when an anchor
    exists, and simply `gross_cube_m3` rounded to four decimals when none does",
    and "A zone is eligible when that remainder is at or above 0.0000, so a zone
    that fills to exactly capacity is eligible."

    PRD.md section 3.3 supplies the blocking edge: "From either of the same two
    states, an order whose target site has just become `FROZEN` moves to
    `BLOCKED_WAREHOUSE` with `blocked_reason` `WAREHOUSE_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/finished_unit_store_gated_by_warehouse_frozen_posture
    """
    ctx = _p2_three_sellable_hulls()

    first = store_unit(ctx, ctx["sellable_units"][0])
    assert_decimal_equals(
        first["stored_footprint_cube_m3"], Decimal("2.0000"), Q_CUBE, "anchor footprint"
    )
    assert first["is_zone_anchor"] is True
    assert first["storage_zone_code"] == "Z-A"

    site_after_first = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_decimal_equals(
        site_after_first["utilization_pct"], Decimal("66.67"), Q_PERCENT, "utilization_pct"
    )
    assert site_after_first["posture"] == "NORMAL"

    second = store_unit(ctx, ctx["sellable_units"][1])
    assert_decimal_equals(
        second["stored_footprint_cube_m3"], Decimal("1.0000"), Q_CUBE, "nested footprint"
    )
    assert second["is_zone_anchor"] is False
    assert second["storage_zone_code"] == "Z-A"

    summary = _p2_summary(ctx)
    assert_decimal_equals(
        summary["utilization_pct"], Decimal("100.00"), Q_PERCENT, "utilization_pct"
    )
    assert summary["posture"] == "FROZEN"
    assert summary["blocked_production_order_count"] == 1
    assert_footprint_summary_consistent(summary)

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "BLOCKED_WAREHOUSE"
    assert order["blocked_reason"] == "WAREHOUSE_FROZEN"

    third = ctx["sellable_units"][2]
    site_before_refusal = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    validate_error(
        api_client.store_finished_unit(
            third["id"],
            store_payload(site_before_refusal["version"]),
            ctx["planner_headers"],
        ),
        ApiErrorId.WAREHOUSE_FROZEN,
        409,
    )

    unchanged = api_client.read_entity(
        "get_finished_unit", third["id"], ctx["planner_headers"]
    )
    assert unchanged["logistics_status"] == "UNALLOCATED"
    assert unchanged["warehouse_id"] is None
    site_after_refusal = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert site_after_refusal["version"] == site_before_refusal["version"], (
        "a refused store must not advance the site version"
    )


def test_release_storage_of_a_non_anchor_sibling_unfreezes_and_unblocks_the_order():
    """Releasing the nested hull is a plain subtraction, and the order returns.

    PRD.md section 3.7: "**Releasing storage** requires `logistics_status`
    `STORED` and a `release_reason`, and is the head of **CASCADE-C**: (1) the hull
    moves `STORED` to `UNALLOCATED`, its `warehouse_id`, `storage_zone_code`,
    `stored_at` and `demand_bucket_id` are cleared, its
    `stored_footprint_cube_m3` is set to 0.0000 and `is_zone_anchor` to false;
    (2) when the released hull *was* its nest group's anchor and followers remain,
    the earliest surviving occupant of the same site-zone-model group ... is
    promoted". The released hull here is *not* the anchor, so link 2 does not
    fire and no promotion inflates the group.

    PRD.md section 3.7 continues: "(3) The site's `committed_cube_m3`,
    `utilization_pct` and `posture` are recomputed. (4) A site that has left
    `FROZEN` returns its orders in `BLOCKED_WAREHOUSE` to `READY_TO_SCHEDULE`,
    subject to those orders having at least one qualified lot."

    Design: Difficulty/cross_entity_state_dependency/finished_unit_store_gated_by_warehouse_frozen_posture
    """
    ctx = _p2_three_sellable_hulls()
    anchor, nested = _p2_fill_the_site(ctx)
    frozen = _p2_summary(ctx)
    assert frozen["posture"] == "FROZEN"

    released = get_success_data(
        api_client.release_storage(
            nested["id"],
            release_storage_payload(release_reason="Space rebalance"),
            ctx["planner_headers"],
        )
    )
    assert released["logistics_status"] == "UNALLOCATED"
    assert released["warehouse_id"] is None
    assert released["storage_zone_code"] is None
    assert released["is_zone_anchor"] is False
    assert_decimal_equals(
        released["stored_footprint_cube_m3"],
        Decimal("0.0000"),
        Q_CUBE,
        "released footprint",
    )

    # No promotion: the surviving hull was already the anchor and keeps its full
    # cube, so the site falls by exactly the nested charge of 1.0000.
    surviving = api_client.read_entity(
        "get_finished_unit", anchor["id"], ctx["planner_headers"]
    )
    assert surviving["is_zone_anchor"] is True
    assert_decimal_equals(
        surviving["stored_footprint_cube_m3"],
        Decimal("2.0000"),
        Q_CUBE,
        "anchor footprint",
    )

    summary = _p2_summary(ctx)
    assert_decimal_equals(
        summary["utilization_pct"], Decimal("66.67"), Q_PERCENT, "utilization_pct"
    )
    assert summary["posture"] == "NORMAL"
    assert_footprint_summary_consistent(summary)

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "READY_TO_SCHEDULE"
    assert order["blocked_reason"] is None


def test_store_gate_is_re_evaluated_so_the_re_issued_store_refreezes_the_site():
    """The refused hull stores once room exists, and the gate closes again.

    PRD.md section 3.7 makes the posture a derived reading rather than a latch:
    "**Posture** is derived, never stored independently: `posture` is `FROZEN`
    when `utilization_pct` is at or above `frozen_threshold_pct`, `RESTRICTED`
    when it is at or above `restricted_threshold_pct` but below the frozen
    threshold, and `NORMAL` otherwise." Both the storage cascade and the release
    cascade recompute "`utilization_pct` ... as `committed_cube_m3` divided by
    `footprint_capacity_cube_m3` times 100, rounded to two decimals", so the hull
    refused with `ERR_WAREHOUSE_FROZEN` is admitted after a sibling's release
    without any change to the hull itself.

    PRD.md section 3.7 fixes the re-admitted footprint: the candidate pays
    "`gross_cube_m3` multiplied by its `nest_factor` and rounded to four decimals
    when an anchor exists", and PRD.md section 3.3 re-applies the blocking edge -
    "an order whose target site has just become `FROZEN` moves to
    `BLOCKED_WAREHOUSE` with `blocked_reason` `WAREHOUSE_FROZEN`" - the moment the
    site is full again.

    Design: Difficulty/cross_entity_state_dependency/finished_unit_store_gated_by_warehouse_frozen_posture
    """
    ctx = _p2_three_sellable_hulls()
    _anchor, nested = _p2_fill_the_site(ctx)
    third = ctx["sellable_units"][2]

    validate_error(
        api_client.store_finished_unit(
            third["id"],
            store_payload(warehouse_version(ctx["warehouse_id"])),
            ctx["planner_headers"],
        ),
        ApiErrorId.WAREHOUSE_FROZEN,
        409,
    )

    get_success_data(
        api_client.release_storage(
            nested["id"],
            release_storage_payload(release_reason="Space rebalance"),
            ctx["planner_headers"],
        )
    )
    set_clock("2026-08-01T11:10:00Z")

    stored = store_unit(ctx, third)
    assert stored["logistics_status"] == "STORED"
    assert stored["storage_zone_code"] == "Z-A"
    assert stored["is_zone_anchor"] is False
    assert_decimal_equals(
        stored["stored_footprint_cube_m3"],
        Decimal("1.0000"),
        Q_CUBE,
        "nested footprint",
    )

    summary = _p2_summary(ctx)
    assert_decimal_equals(
        summary["utilization_pct"], Decimal("100.00"), Q_PERCENT, "utilization_pct"
    )
    assert summary["posture"] == "FROZEN"
    assert summary["blocked_production_order_count"] == 1
    assert_footprint_summary_consistent(summary)

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "BLOCKED_WAREHOUSE"
    assert order["blocked_reason"] == "WAREHOUSE_FROZEN"
