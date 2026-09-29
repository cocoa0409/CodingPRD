"""Corner validations, bands 6 and 7: instants and aggregates at their exact bounds.

PRD.md section 2.7 places these two families of check next to each other in the ascending
ladder every endpoint follows: "**Referential agreement and temporal constraints** —
cross-entity field agreement, oven and mould window conflicts, past-dated oven starts,
warehouse/trailer origin agreement, build-ahead window membership and warranty term",
followed by "**Capacity, quota and money** — mould eligibility and
occupancy, cooling-bay slots, resin sufficiency, zone and site cube, build-ahead quota,
trailer cube and payload, order overbuild, and warranty reserve sufficiency".

Each test drives a pair of requests one quantum apart across the bound — one second of
clock, one ten-thousandth of a cubic metre, one hundredth of a percent — so that the
accepted request proves the rule is not vacuous and the refused one proves it is not
absent. PRD.md section 2.2 fixes the shape of every refusal, and PRD.md section 2.10 its
extent: "when any validation the triggering request declares fails, nothing at all is
persisted: no child row, no ledger movement, no status change, no version increment."
"""

from test_helpers import (
    DEFAULT_ZONE_CODE,
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    approve_claim_payload,
    assert_decimal_equals,
    assert_instant_equals,
    assert_warranty_reserve_conserved,
    create_customer,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    mold_payload,
    molding_cycle_payload,
    product_model_version,
    production_order_version,
    set_clock,
    setup_delivered_units,
    setup_stored_units,
    shipment_line_payload,
    shipment_payload,
    shipment_version,
    storage_review_payload,
    validate_error,
    validate_paginated,
    validate_success,
    waive_storage_finding_payload,
    warranty_claim_payload,
    zone,
)

# The two trailer tests below need the same unusual plant: a hull whose gross cube is
# 1.2345 m3 nesting at half that, and a four-cavity tool so that one cycle yields the
# four hulls the two trailers share. PRD.md section 2.8 requires a tool's
# `nominal_charge_kg` to "equal the model's `nominal_charge_kg` multiplied by
# `cavity_count`", which fixes 10.000 * 4 == 40.000, and PRD.md section 3.3 caps the
# hulls an order may schedule at `ordered_qty` times 1.20 floored, so `ordered_qty` is 4.
_P6_TRAILER_MODEL = {
    "gross_cube_m3": 1.2345,
    "nest_factor": 0.5,
    "unit_weight_kg": 30.0,
    "nominal_charge_kg": 10.0,
}


def _p6_four_stored_hulls():
    """Four SELLABLE hulls of the 1.2345 m3 model, all STORED at one roomy site."""
    return setup_stored_units(
        model_overrides=dict(_P6_TRAILER_MODEL),
        mold_overrides={"cavity_count": 4, "nominal_charge_kg": 40.0},
        warehouse_overrides={
            "footprint_capacity_cube_m3": 100.0,
            "zones": [zone(DEFAULT_ZONE_CODE, 100.0)],
        },
        order_overrides={"ordered_qty": 4},
        lot_overrides={"received_kg": 100.0},
        charge_overrides={"charge_kg": 40.0, "regrind_kg": 4.0},
    )


def test_oven_start_exactly_at_the_clock_is_scheduled_and_one_second_earlier_is_refused(
    api, admin_headers
):
    """The past-dating rung is a closed lower bound at the clock instant.

    PRD.md section 3.4: "`oven_start_at` must be at or after the logical clock — equality
    passes — otherwise `ERR_OVEN_START_IN_PAST` (HTTP 422); cycles may not be back-dated."
    The three attempts below sit one second apart around that bound, so an implementation
    using a strict comparison fails the first attempt and one ignoring the clock passes
    the second.

    The refused attempt is deliberately booked on arm 2, because PRD.md section 3.4 ranks
    the arm check after this one — "Then the oven arm window, then the bay slot count,
    then the mould pool, then the overbuild ceiling, and last of all
    `expected_production_order_version`" — and an arm-1 booking would be explicable by
    `ERR_OVEN_WINDOW_CONFLICT` instead.  For the same reason the refusal reuses the very
    version the next accepted call also uses, which PRD.md section 3.4 makes observable:
    "A refused booking writes nothing at all — no cycle row, no order version bump."

    The second accepted cycle must draw the *other* tool, because PRD.md section 3.4 makes
    occupancy half-open — "The span compared is the half-open interval from
    `oven_start_at` up to but not including `cooling_window_end_at`" — and 09:00:01Z falls
    inside the first cycle's span.  Which tool comes first is fixed by the tie-break
    "ascending `cycles_since_service`, then ascending `mold_code`", both tools sitting at
    0 cycles.

    Design: Corner/validations/val_temporal_oven_start_at_the_clock_passes_one_second_earlier_fails
    """
    # Single-cavity tools, so that the order's overbuild ceiling of
    # floor(2 * 1.20) == 2 hulls admits both cycles below.
    single_cavity = {"cavity_count": 1, "nominal_charge_kg": 12.0}
    ctx = create_plant_baseline(mold_overrides=dict(single_cavity))
    operator_headers = ctx["operator_headers"]
    first_mold = ctx["mold"]
    second_mold = validate_success(
        api.create_mold(
            mold_payload(ctx["product_model_id"], **single_cavity), admin_headers
        ),
        201,
    )
    by_code = sorted([first_mold, second_mold], key=lambda tool: tool["mold_code"])

    create_resin_lot()
    order = create_production_order(ctx, ordered_qty=2)
    assert order["status"] == "READY_TO_SCHEDULE"

    set_clock("2026-08-01T09:00:00Z")

    def cycle_body(*, arm_index, oven_start_at, order_version):
        return molding_cycle_payload(
            order["id"],
            ctx["oven_station_id"],
            ctx["cooling_bay_id"],
            order_version,
            arm_index=arm_index,
            oven_start_at=oven_start_at,
        )

    # Equality with the clock passes.
    at_the_clock = validate_success(
        api.create_molding_cycle(
            cycle_body(
                arm_index=1,
                oven_start_at="2026-08-01T09:00:00Z",
                order_version=production_order_version(order["id"]),
            ),
            operator_headers,
        ),
        201,
    )
    assert at_the_clock["status"] == "SCHEDULED"
    assert_instant_equals(
        at_the_clock["oven_end_at"], "2026-08-01T10:00:00Z", "oven_end_at"
    )
    assert_instant_equals(
        at_the_clock["cooling_window_start_at"],
        "2026-08-01T10:00:00Z",
        "cooling_window_start_at",
    )
    assert_instant_equals(
        at_the_clock["cooling_window_end_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_end_at",
    )
    assert at_the_clock["mold_id"] == by_code[0]["id"], (
        "the mould pool ranks by ascending cycles_since_service then ascending mold_code"
    )

    # One second of back-dating is refused, on an arm no other cycle occupies.
    version_before_refusal = production_order_version(order["id"])
    back_dated = api.create_molding_cycle(
        cycle_body(
            arm_index=2,
            oven_start_at="2026-08-01T08:59:59Z",
            order_version=version_before_refusal,
        ),
        operator_headers,
    )
    validate_error(back_dated, ApiErrorId.OVEN_START_IN_PAST, 422)

    # One second into the future is admitted, and the SAME order version still works,
    # which proves the refusal above bumped nothing.
    one_second_late = validate_success(
        api.create_molding_cycle(
            cycle_body(
                arm_index=2,
                oven_start_at="2026-08-01T09:00:01Z",
                order_version=version_before_refusal,
            ),
            operator_headers,
        ),
        201,
    )
    assert one_second_late["status"] == "SCHEDULED"
    assert one_second_late["mold_id"] == by_code[1]["id"], (
        "the first tool is occupied over the half-open span containing 09:00:01Z"
    )
    assert_instant_equals(
        one_second_late["oven_end_at"], "2026-08-01T10:00:01Z", "oven_end_at"
    )
    assert_instant_equals(
        one_second_late["cooling_window_end_at"],
        "2026-08-01T10:30:01Z",
        "cooling_window_end_at",
    )

    # Exactly two rows for three attempts, and one version bump per accepted row.
    cycles, meta = validate_paginated(
        api.list_molding_cycles({"production_order_id": order["id"]}, operator_headers)
    )
    assert meta["total_count"] == 2, "the refused booking left no cycle row"
    assert {cycle["status"] for cycle in cycles} == {"SCHEDULED"}
    assert sorted(cycle["arm_index"] for cycle in cycles) == [1, 2]

    closing = api.read_entity("get_production_order", order["id"], admin_headers)
    assert closing["status"] == "IN_PRODUCTION"
    assert closing["version"] == order["version"] + 2


def test_acknowledgement_at_the_delivery_instant_verifies_and_one_second_later_does_not(
    api, admin_headers, planner_headers, warranty_agent_headers
):
    """Two claimants one second apart around the same delivery diverge on the storage axis.

    PRD.md section 3.9: "An outcome of `VERIFIED` additionally requires that the customer's
    `storage_guidance_acknowledged_at` is not null **and** falls at or before the hull's
    `delivered_at`, otherwise `ERR_STORAGE_GUIDANCE_NOT_ACKNOWLEDGED` (HTTP 422); an
    acknowledgement timestamp exactly equal to `delivered_at` passes, one dated after
    delivery does not, because the guidance must have been read before the boat arrived."
    A comparison in the wrong direction, or one truncated to the calendar date, passes both
    claims; a strict comparison refuses both.

    The late claimant's only remaining route is the one PRD.md section 3.9 leaves open —
    "`VIOLATED` sets it to `GUIDANCE_VIOLATED`", an outcome that carries no acknowledgement
    precondition — followed by PRD.md section 3.9's waiver: "The axis must read
    `GUIDANCE_VIOLATED`, otherwise `ERR_STORAGE_FINDING_NOT_WAIVABLE` (HTTP 409) ... The
    axis becomes `WAIVED`. A waiver unblocks approval but does **not** restore full value:
    the 35.00 percent storage deduction still applies to a claim approved from `WAIVED`."

    The payout then exposes the ordering of PRD.md section 3.9's pricing steps, in
    particular that the fee tier "is chosen **once, from the gross, before any deduction**,
    and is never re-selected against the reduced amount", so the waiver costs the claimant
    the deduction and nothing more.  The age is frozen by PRD.md section 3.9: start-review
    "computes and freezes `months_in_service` as the number of **complete calendar months**
    from the hull's `delivered_at` to the logical clock, floored".

    Design: Corner/validations/val_temporal_storage_acknowledgement_at_delivery_passes_one_second_late_fails
    """
    delivered_at = "2026-08-01T12:00:00Z"
    ctx = setup_delivered_units(
        delivered_at=delivered_at,
        model_overrides={"msrp_cents": 400020, "initial_warranty_reserve_cents": 1000000},
    )
    model_id = ctx["product_model_id"]
    hull_on_time, hull_late = ctx["delivered_units"][0], ctx["delivered_units"][1]
    assert_instant_equals(hull_on_time["delivered_at"], delivered_at, "delivered_at")
    assert_instant_equals(hull_late["delivered_at"], delivered_at, "delivered_at")

    # The clock stands at the delivery instant, so this acknowledgement is dated exactly
    # at delivery however the stamp is sourced.
    on_time = create_customer(acknowledged_at=delivered_at)
    assert_instant_equals(
        on_time["customer"]["storage_guidance_acknowledged_at"],
        delivered_at,
        "storage_guidance_acknowledged_at",
    )

    # One second later, again with the clock in step.
    set_clock("2026-08-01T12:00:01Z")
    late = create_customer(acknowledged_at="2026-08-01T12:00:01Z")
    assert_instant_equals(
        late["customer"]["storage_guidance_acknowledged_at"],
        "2026-08-01T12:00:01Z",
        "storage_guidance_acknowledged_at",
    )

    model_before = api.read_entity("get_product_model", model_id, admin_headers)
    assert model_before["warranty_reserve_cents"] == 1000000
    assert model_before["warranty_paid_cents"] == 0

    # Seven complete calendar months after delivery.
    set_clock("2027-03-01T12:00:00Z")

    claim_on_time = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                hull_on_time["id"], on_time["customer_id"], reported_deformation_mm=3.5
            ),
            warranty_agent_headers,
        ),
        201,
    )
    reviewing = validate_success(
        api.start_claim_review(claim_on_time["id"], warranty_agent_headers)
    )
    assert reviewing["months_in_service"] == 7
    verified = validate_success(
        api.submit_storage_review(
            claim_on_time["id"], storage_review_payload("VERIFIED"), warranty_agent_headers
        )
    )
    assert verified["storage_review_status"] == "GUIDANCE_VERIFIED"
    assert verified["claim_status"] == "UNDER_REVIEW"

    claim_late = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                hull_late["id"], late["customer_id"], reported_deformation_mm=3.5
            ),
            warranty_agent_headers,
        ),
        201,
    )
    validate_success(api.start_claim_review(claim_late["id"], warranty_agent_headers))

    refused = api.submit_storage_review(
        claim_late["id"], storage_review_payload("VERIFIED"), warranty_agent_headers
    )
    validate_error(refused, ApiErrorId.STORAGE_GUIDANCE_NOT_ACKNOWLEDGED, 422)

    # Neither axis moved: the refused review is not a partial decision.
    held = api.read_entity("get_warranty_claim", claim_late["id"], warranty_agent_headers)
    assert held["storage_review_status"] == "NOT_STARTED"
    assert held["claim_status"] == "UNDER_REVIEW"

    violated = validate_success(
        api.submit_storage_review(
            claim_late["id"], storage_review_payload("VIOLATED"), warranty_agent_headers
        )
    )
    assert violated["storage_review_status"] == "GUIDANCE_VIOLATED"

    waived = validate_success(
        api.waive_storage_finding(
            claim_late["id"], waive_storage_finding_payload(), admin_headers
        )
    )
    assert waived["storage_review_status"] == "WAIVED"
    assert waived["claim_status"] == "UNDER_REVIEW"

    approved = validate_success(
        api.approve_warranty_claim(
            claim_late["id"],
            approve_claim_payload(product_model_version(model_id)),
            warranty_agent_headers,
        )
    )
    assert approved["claim_status"] == "APPROVED"
    assert approved["months_in_service"] == 7
    assert approved["payout_basis"] == "PRO_RATA_AGE"
    # Coverage is (60 - 7) / 60 * 100 == 88.33 percent of an MSRP of 400020 at the
    # HULL_DEFORMATION factor 1.00.
    assert approved["pre_fee_gross_cents"] == 353338
    assert approved["admin_fee_cents"] == 17667
    assert approved["storage_deduction_cents"] == 123668
    assert approved["net_payout_cents"] == 212003
    # The waiver costs exactly the deduction: had the axis been GUIDANCE_VERIFIED the same
    # claim would have paid 353338 - 0 - 17667 == 335671, with the IDENTICAL fee, because
    # the tier was chosen from the gross before the deduction was taken.
    assert approved["net_payout_cents"] + approved["storage_deduction_cents"] == 335671

    model_after = api.read_entity("get_product_model", model_id, admin_headers)
    assert model_after["warranty_reserve_cents"] == 1000000 - 212003
    assert model_after["warranty_paid_cents"] == 212003
    assert model_after["version"] == model_before["version"] + 1
    assert_warranty_reserve_conserved(model_after)

    # The on-time claim was never approved, so it contributed nothing to that arithmetic.
    untouched = api.read_entity(
        "get_warranty_claim", claim_on_time["id"], warranty_agent_headers
    )
    assert untouched["claim_status"] == "UNDER_REVIEW"
    assert untouched["storage_review_status"] == "GUIDANCE_VERIFIED"
    assert untouched["pre_fee_gross_cents"] is None
    assert untouched["admin_fee_cents"] is None
    assert untouched["storage_deduction_cents"] is None
    assert untouched["net_payout_cents"] is None

    # Neither the planner headers nor the site were needed for the money, but the
    # delivered hulls must still read DELIVERED for the approve rung above to have been
    # the reachable one.
    for hull in (hull_on_time, hull_late):
        current = api.read_entity("get_finished_unit", hull["id"], planner_headers)
        assert current["logistics_status"] == "DELIVERED"


def test_a_trailer_rounding_up_to_60_00_seals_while_59_99_is_underutilized(
    api, planner_headers
):
    """The seal minimum is compared against the rounded utilisation, not the raw quotient.

    PRD.md section 3.8 defines the figure: "`cube_utilization_pct` is `nested_cube_m3`
    divided by `trailer_cube_capacity_m3` times 100, rounded to two decimals".  The seal
    rung then tests exactly that field: "its `cube_utilization_pct` must be at or above the
    minimum seal utilisation of 60.00 percent (`ERR_TRAILER_UNDERUTILIZED`, HTTP 409, with
    exactly 60.00 passing)".

    Both trailers carry the identical load, so `trailer_cube_capacity_m3` is the only
    difference between them: 1.8518 / 3.0865 * 100 is 59.996760..., which rounds to 60.00
    and seals, while 1.8518 / 3.0866 * 100 is 59.994816..., which rounds to 59.99 and does
    not.  An implementation comparing the raw quotient against 60.00 refuses the first
    trailer too.

    The nested figure itself follows PRD.md section 3.8: "A line's `line_nested_cube_m3` is
    the full gross cube when its `nest_position` is 1, and `gross_cube_m3` multiplied by
    `nest_factor`, rounded to four decimals, for every position after the first."

    Design: Corner/validations/val_violation_trailer_underutilized_when_the_rounded_utilisation_slips_below_60
    """
    ctx = _p6_four_stored_hulls()
    hulls = ctx["stored_units"]
    assert len(hulls) == 4

    seals_at_sixty = validate_success(
        api.create_shipment(
            shipment_payload(
                ctx["warehouse_id"],
                trailer_cube_capacity_m3=3.0865,
                trailer_max_payload_kg=1000.0,
            ),
            planner_headers,
        ),
        201,
    )
    one_hundredth_short = validate_success(
        api.create_shipment(
            shipment_payload(
                ctx["warehouse_id"],
                trailer_cube_capacity_m3=3.0866,
                trailer_max_payload_kg=1000.0,
            ),
            planner_headers,
        ),
        201,
    )

    def load(shipment, hull):
        return validate_success(
            api.create_shipment_line(
                shipment_line_payload(
                    shipment["id"], hull["id"], shipment_version(shipment["id"])
                ),
                planner_headers,
            ),
            201,
        )

    load(seals_at_sixty, hulls[0])
    load(seals_at_sixty, hulls[1])
    load(one_hundredth_short, hulls[2])
    load(one_hundredth_short, hulls[3])

    # The two loads are identical to the last decimal.
    for shipment in (seals_at_sixty, one_hundredth_short):
        loaded = api.read_entity("get_shipment", shipment["id"], planner_headers)
        assert_decimal_equals(loaded["nested_cube_m3"], 1.8518, Q_CUBE, "nested_cube_m3")
        assert_decimal_equals(loaded["loaded_weight_kg"], 60.0, Q_MASS, "loaded_weight_kg")
        assert loaded["status"] == "LOADING"

    rounds_up = api.read_entity("get_shipment", seals_at_sixty["id"], planner_headers)
    assert_decimal_equals(
        rounds_up["cube_utilization_pct"], 60.0, Q_PERCENT, "cube_utilization_pct"
    )
    rounds_down = api.read_entity("get_shipment", one_hundredth_short["id"], planner_headers)
    assert_decimal_equals(
        rounds_down["cube_utilization_pct"], 59.99, Q_PERCENT, "cube_utilization_pct"
    )

    set_clock("2026-08-01T11:00:00Z")

    sealed = validate_success(api.seal_shipment(seals_at_sixty["id"], planner_headers))
    assert sealed["status"] == "SEALED"
    assert_instant_equals(sealed["sealed_at"], "2026-08-01T11:00:00Z", "sealed_at")
    assert sealed["quoted_freight_cents"] is not None

    refused = api.seal_shipment(one_hundredth_short["id"], planner_headers)
    validate_error(refused, ApiErrorId.TRAILER_UNDERUTILIZED, 409)

    # A refused seal mints no quote and unloads nothing.
    after = api.read_entity("get_shipment", one_hundredth_short["id"], planner_headers)
    assert after["status"] == "LOADING"
    assert after["sealed_at"] is None
    assert after["quoted_freight_cents"] is None

    lines, meta = validate_paginated(
        api.list_shipment_lines(
            {"shipment_id": one_hundredth_short["id"]}, planner_headers
        )
    )
    assert meta["total_count"] == 2, "the trailer is not empty, so it is not ERR_SHIPMENT_EMPTY"
    assert {line["status"] for line in lines} == {"LOADED"}
    for hull in (hulls[2], hulls[3]):
        current = api.read_entity("get_finished_unit", hull["id"], planner_headers)
        assert current["logistics_status"] == "LOADED"


def test_the_second_line_at_the_inclusive_cube_bound_passes_and_one_unit_over_fails(
    api, planner_headers
):
    """Each hull fits alone; only the post-addition aggregate decides.

    PRD.md section 3.8: "The candidate's nested contribution — full gross cube if it would
    take position 1 in its model group, nested cube otherwise — is added to
    `nested_cube_m3`, rounded to four decimals, and must be at or below
    `trailer_cube_capacity_m3`, otherwise `ERR_TRAILER_CUBE_EXCEEDED` (HTTP 409). ... Both
    are at-or-below, so a hull that fills the trailer to exactly its cube capacity or
    exactly its payload ceiling is accepted."

    The two trailers differ by one ten-thousandth of a cubic metre, and the pair of hulls
    rolls up to 1.2345 + 0.6173 == 1.8518: exactly the first trailer's capacity, one unit
    over the second's.  Both first lines are charged the full gross cube, which PRD.md
    section 3.8 makes per-trailer — "a line's `nest_position` is one plus the number of
    earlier lines whose hull shares the same `product_model_id`" — even though siblings of
    the same model are nested behind an anchor back at the warehouse.

    The payload rung cannot be confused for the cube rung: at 30.000 kg a hull the pair
    weighs 60.000 kg against a 1000.000 kg ceiling.  And PRD.md section 3.8 fixes the
    extent of the refusal: "The candidate is tested **before** the row is written: a
    rejected line leaves no `ShipmentLine` behind, does not touch the hull, and does not
    advance the shipment's `version`, so a caller may retry with the same
    `expected_shipment_version`."

    Design: Corner/validations/val_aggregate_trailer_cube_exceeded_by_the_second_line_at_the_inclusive_bound
    """
    ctx = _p6_four_stored_hulls()
    hulls = ctx["stored_units"]

    exact_fit = validate_success(
        api.create_shipment(
            shipment_payload(
                ctx["warehouse_id"],
                trailer_cube_capacity_m3=1.8518,
                trailer_max_payload_kg=1000.0,
            ),
            planner_headers,
        ),
        201,
    )
    one_unit_short = validate_success(
        api.create_shipment(
            shipment_payload(
                ctx["warehouse_id"],
                trailer_cube_capacity_m3=1.8517,
                trailer_max_payload_kg=1000.0,
            ),
            planner_headers,
        ),
        201,
    )

    # The first line on each trailer is position 1 of its model group and pays the full
    # gross cube, which is under either capacity: each hull fits individually.
    for shipment, hull in ((exact_fit, hulls[0]), (one_unit_short, hulls[2])):
        anchor_line = validate_success(
            api.create_shipment_line(
                shipment_line_payload(
                    shipment["id"], hull["id"], shipment_version(shipment["id"])
                ),
                planner_headers,
            ),
            201,
        )
        assert anchor_line["nest_position"] == 1
        assert_decimal_equals(
            anchor_line["line_nested_cube_m3"], 1.2345, Q_CUBE, "line_nested_cube_m3"
        )
        rolled = api.read_entity("get_shipment", shipment["id"], planner_headers)
        assert_decimal_equals(rolled["nested_cube_m3"], 1.2345, Q_CUBE, "nested_cube_m3")

    # Equality with the capacity is accepted.
    nested_line = validate_success(
        api.create_shipment_line(
            shipment_line_payload(
                exact_fit["id"], hulls[1]["id"], shipment_version(exact_fit["id"])
            ),
            planner_headers,
        ),
        201,
    )
    assert nested_line["nest_position"] == 2
    assert_decimal_equals(
        nested_line["line_nested_cube_m3"], 0.6173, Q_CUBE, "line_nested_cube_m3"
    )
    filled = api.read_entity("get_shipment", exact_fit["id"], planner_headers)
    assert_decimal_equals(filled["nested_cube_m3"], 1.8518, Q_CUBE, "nested_cube_m3")
    assert_decimal_equals(
        filled["cube_utilization_pct"], 100.0, Q_PERCENT, "cube_utilization_pct"
    )

    # One ten-thousandth of a cubic metre less capacity refuses the identical second hull.
    version_before = shipment_version(one_unit_short["id"])
    over = api.create_shipment_line(
        shipment_line_payload(one_unit_short["id"], hulls[3]["id"], version_before),
        planner_headers,
    )
    validate_error(over, ApiErrorId.TRAILER_CUBE_EXCEEDED, 409)

    # Nothing was written, so the same declared version is still current.
    refused_trailer = api.read_entity("get_shipment", one_unit_short["id"], planner_headers)
    assert refused_trailer["status"] == "LOADING"
    assert refused_trailer["version"] == version_before
    assert_decimal_equals(
        refused_trailer["nested_cube_m3"], 1.2345, Q_CUBE, "nested_cube_m3"
    )
    assert_decimal_equals(
        refused_trailer["loaded_weight_kg"], 30.0, Q_MASS, "loaded_weight_kg"
    )
    assert_decimal_equals(
        refused_trailer["cube_utilization_pct"], 66.67, Q_PERCENT, "cube_utilization_pct"
    )

    lines, meta = validate_paginated(
        api.list_shipment_lines({"shipment_id": one_unit_short["id"]}, planner_headers)
    )
    assert meta["total_count"] == 1, "the refused line left no ShipmentLine behind"
    assert lines[0]["status"] == "LOADED"

    # The refused candidate never left the warehouse.
    stranded = api.read_entity("get_finished_unit", hulls[3]["id"], planner_headers)
    assert stranded["logistics_status"] == "STORED"
    assert stranded["storage_zone_code"] == DEFAULT_ZONE_CODE
    assert_decimal_equals(
        stranded["stored_footprint_cube_m3"], 0.6173, Q_CUBE, "stored_footprint_cube_m3"
    )
