"""Corner validations: the checks that only apply to some requests, and the
aggregates that bind exactly at their ceiling.

PRD.md section 2.7 opens the priority ladder with the sentence every test in this
module leans on: "Each endpoint evaluates its applicable checks in a fixed
ascending priority order and returns on the first failure it finds; no endpoint
reports two errors, and no later check runs after an earlier one has failed."
The word *applicable* is what is probed here.  A check keyed on the shape of the
request — on the producing order's `demand_bucket_id`, on the claim's
`claim_type` — has to stay silent on a request outside its scope, so each test
pairs the request the check refuses with the otherwise identical request it must
not touch.  Without that pair a passing assertion proves nothing: an
implementation that applied the rule to everything, or to nothing, would still
satisfy half of it.

Two of the four tests pin an aggregate at its bound instead.  PRD.md section 2.11
says why the bound may be probed by replay: "No derived value in this service is
an independently maintained counter that can drift. Each is defined as an
aggregate over a named row set with a named status filter, and each is recomputed
from that set inside every request that could change it."  An aborted cycle or a
bucket-less hull is therefore not merely uncounted from now on; it was never a
member of the set being summed.

PRD.md section 2.10 supplies the "nothing was written" half of every refusal:
"When any link of a cascade cannot be applied, or when any validation the
triggering request declares fails, nothing at all is persisted: no child row, no
ledger movement, no status change, no version increment."
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    DEFAULT_OVEN_START,
    DEFAULT_ZONE_CODE,
    Q_CUBE,
    Q_PERCENT,
    abort_payload,
    advance_unit_to_sellable,
    assert_instant_equals,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    create_demand_bucket,
    create_production_order,
    mold_payload,
    molding_cycle_payload,
    production_order_version,
    reserve_charge,
    run_cycle_to_demold,
    schedule_cycle,
    set_clock,
    setup_delivered_unit_with_customer,
    setup_scheduled_cycle,
    setup_sellable_units,
    store_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warehouse_payload,
    warehouse_version,
    warranty_claim_payload,
    zone,
)

# A model whose hulls cube to a round 1.0000 m3 and nest at exactly half, so the
# zone arithmetic below reads off the PRD's rounding rule without a residue.
_P6_ROUND_CUBE_MODEL = {"gross_cube_m3": 1.0, "nest_factor": 0.5}

# PRD.md section 2.8 declares `reported_deformation_mm` at two decimals, and the
# shared helpers publish no two-decimal millimetre quantum, so this module names
# its own rather than borrowing the percentage one.
_P6_Q_MM = Decimal("0.01")


def _p6_second_cycle_of_hulls(ctx, order, *, oven_start_at, oven_end_at, cooling_end_at):
    """Run one more cycle of the context's plant on ``order`` and finish its hulls.

    The shared fixtures build a single cycle per context, but two of the tests
    here need two orders that differ only in one field, so the second order's
    hulls have to be minted by hand.  Nothing here is under test: the cycle uses
    the context's own oven, bay and mould, its span is disjoint from the first
    cycle's, and the returned hulls are SELLABLE and UNALLOCATED.
    """
    cycle = schedule_cycle(ctx, order, oven_start_at=oven_start_at)
    reserve_charge(ctx, cycle, ctx["resin_lot"])
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    run_cycle_to_demold(
        ctx,
        actual_oven_start_at=oven_start_at,
        actual_oven_end_at=oven_end_at,
        actual_cooling_end_at=cooling_end_at,
    )
    return [advance_unit_to_sellable(ctx, unit) for unit in ctx["finished_units"]]


def test_the_overbuild_ceiling_binds_on_the_third_cycle_and_an_abort_hands_the_quota_back(
    api, admin_headers
):
    """The third single-cavity cycle of a two-hull order is one hull too many.

    PRD.md section 3.3: "Finally, an **overbuild ceiling** protects the order from
    unbounded scheduling: the number of scheduled plus completed hulls for an
    order may not exceed `ordered_qty` multiplied by 1.20 and floored to an
    integer. A cycle that would breach it is refused with `ERR_ORDER_OVERBUILD`
    (HTTP 409)."  At an `ordered_qty` of 2 the ceiling is the floor of 2.40, which
    is 2, so two single-cavity cycles exhaust it exactly and the third is refused.

    Three tools exist and only two are booked, which is what makes the refusal
    attributable: PRD.md section 3.4 orders the scheduling checks "Then the oven
    arm window, then the bay slot count, then the mould pool, then the overbuild
    ceiling, and last of all `expected_production_order_version`", so a third arm,
    a third free tool and a bay with three slots leave the ceiling as the only
    check that can speak.

    The abort then proves the ceiling is recomputed rather than tallied.  PRD.md
    section 2.11: "No derived value in this service is an independently maintained
    counter that can drift. Each is defined as an aggregate over a named row set
    with a named status filter, and each is recomputed from that set inside every
    request that could change it."  An `ABORTED` cycle is neither scheduled nor
    completed, and PRD.md section 3.5 confirms the abort touches nothing else that
    matters here: "Aborting from `SCHEDULED` is the head of **CASCADE-A**: (1) the
    cycle becomes `ABORTED` with `abort_reason` `OPERATOR_ABORT`; (2) every charge
    of the cycle in `RESERVED` becomes `RELEASED` ... and (4) orders in
    `BLOCKED_RESIN` that those lots qualify for move to `READY_TO_SCHEDULE`, or to
    `BLOCKED_WAREHOUSE` when the target site is `FROZEN`" — this order is
    `IN_PRODUCTION` and its cycles carry no charges, so its own `version` is
    untouched and the refused body can be replayed byte for byte.

    Design: Corner/validations/val_aggregate_order_overbuild_ceiling_binds_on_the_third_cycle
    """
    single_cavity = {"cavity_count": 1, "nominal_charge_kg": 12.0}
    ctx = setup_scheduled_cycle(
        charge=False,
        mold_overrides=dict(single_cavity),
        station_overrides={"arm_count": 3},
        bay_overrides={"concurrent_slot_capacity": 3},
        order_overrides={"ordered_qty": 2},
        lot_overrides={"received_kg": 100.0},
    )
    operator_headers = ctx["operator_headers"]
    order = ctx["production_order"]
    order_id = ctx["production_order_id"]

    first_cycle = ctx["molding_cycle"]
    assert first_cycle["arm_index"] == 1
    assert first_cycle["mold_id"] == ctx["mold_id"]
    assert_instant_equals(
        first_cycle["oven_start_at"], DEFAULT_OVEN_START, "oven_start_at"
    )

    # Two further single-cavity tools of the same model. All three start at
    # cycles_since_service 0, so PRD.md section 3.4's tie-break "ascending
    # `mold_code`" fixes the order in which they are drawn, and the codes the
    # factory mints are monotone in creation order.
    second_mold = validate_success(
        api.create_mold(
            mold_payload(ctx["product_model_id"], **single_cavity), admin_headers
        ),
        201,
    )
    third_mold = validate_success(
        api.create_mold(
            mold_payload(ctx["product_model_id"], **single_cavity), admin_headers
        ),
        201,
    )
    assert ctx["mold"]["mold_code"] < second_mold["mold_code"] < third_mold["mold_code"]

    second_cycle = schedule_cycle(ctx, order, arm_index=2)
    assert second_cycle["arm_index"] == 2
    assert second_cycle["mold_id"] == second_mold["id"]
    assert second_cycle["status"] == "SCHEDULED"

    # Two scheduled hulls against a ceiling of 2. The third booking is defective
    # in one way only.
    version_before_the_refusal = production_order_version(order_id)
    third_body = molding_cycle_payload(
        order_id,
        ctx["oven_station_id"],
        ctx["cooling_bay_id"],
        version_before_the_refusal,
        arm_index=3,
    )
    refused = api.create_molding_cycle(third_body, operator_headers)
    validate_error(refused, ApiErrorId.ORDER_OVERBUILD, 409)

    # Nothing was written by the refusal: two cycles, and the order's version is
    # exactly where it stood.
    rows, meta = validate_paginated(
        api.list_molding_cycles({"production_order_id": order_id}, operator_headers)
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["SCHEDULED", "SCHEDULED"]
    assert production_order_version(order_id) == version_before_the_refusal
    order_now = api.read_entity("get_production_order", order_id, admin_headers)
    assert order_now["status"] == "IN_PRODUCTION"
    assert order_now["completed_qty"] == 0
    unbooked = api.read_entity("get_mold", third_mold["id"], admin_headers)
    assert unbooked["status"] == "AVAILABLE"
    assert unbooked["cycles_since_service"] == 0

    # Aborting the second cycle removes its hull from the counted set.
    aborted = validate_success(
        api.abort_molding_cycle(second_cycle["id"], abort_payload(), operator_headers)
    )
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == "OPERATOR_ABORT"
    assert aborted["version"] == second_cycle["version"] + 1
    freed_mold = api.read_entity("get_mold", second_mold["id"], admin_headers)
    assert freed_mold["status"] == "AVAILABLE"
    assert freed_mold["cycles_since_service"] == 0, (
        "no part was produced, so the abort may not wear the tool"
    )
    assert production_order_version(order_id) == version_before_the_refusal

    # The byte-identical body is now accepted, and draws the tool the abort freed:
    # the freed tool and the never-booked one tie on cycles_since_service 0 and
    # the lower mold_code wins.
    accepted = validate_success(api.create_molding_cycle(third_body, operator_headers), 201)
    assert accepted["arm_index"] == 3
    assert accepted["mold_id"] == second_mold["id"]
    assert accepted["status"] == "SCHEDULED"
    assert_instant_equals(
        accepted["oven_start_at"], third_body["oven_start_at"], "oven_start_at"
    )

    rows, meta = validate_paginated(
        api.list_molding_cycles({"production_order_id": order_id}, operator_headers)
    )
    assert meta["total_count"] == 3
    assert sorted(row["status"] for row in rows) == ["ABORTED", "SCHEDULED", "SCHEDULED"]
    by_id = {row["id"]: row for row in rows}
    assert by_id[second_cycle["id"]]["status"] == "ABORTED"
    assert by_id[first_cycle["id"]]["status"] == "SCHEDULED"
    assert by_id[accepted["id"]]["status"] == "SCHEDULED"

    molds, mold_meta = validate_paginated(
        api.list_molds({"product_model_id": ctx["product_model_id"]}, admin_headers)
    )
    assert mold_meta["total_count"] == 3
    assert [tool["cycles_since_service"] for tool in molds] == [0, 0, 0], (
        "only a completed demould wears a tool"
    )


def test_build_ahead_window_and_cap_bind_only_on_hulls_from_a_bucket_bearing_order(
    api, planner_headers
):
    """Two identical hulls at one site, told apart only by their order's bucket.

    PRD.md section 3.7 makes both build-ahead gates conditional in one clause:
    "Second, when the producing order names a `demand_bucket_id`, the logical
    clock's calendar date must lie inside that bucket's window from
    `window_start_on` through `window_end_on`, **both bounds inclusive**, otherwise
    `ERR_BUILD_AHEAD_WINDOW_MISMATCH` (HTTP 409) — and when the date is out of
    window the quota check is never reached at all."  The hull from the bucket-less
    order is therefore stored at the very same instant, on the very same warehouse
    version, that the bucket-bearing hull is refused.

    The quota is the second half.  PRD.md section 3.7: "A bucket's
    `build_ahead_cap_qty` is the floor of `forecast_qty` multiplied by
    `build_ahead_cap_pct` divided by 100. Its `build_ahead_committed_qty` is the
    count of hulls whose `demand_bucket_id` is this bucket, whose `build_status` is
    `SELLABLE` and whose `logistics_status` is `STORED` or `LOADED`. The admission
    test at store time is applied to the post-increment count: when
    `build_ahead_committed_qty` plus 1 exceeds `build_ahead_cap_qty` the store is
    refused with `ERR_BUILD_AHEAD_CAP_EXCEEDED` (HTTP 409). Storing the hull that
    lands exactly *on* the cap is accepted; the next one is refused."  At a
    `forecast_qty` of 2 and a cap percentage of 60.00 the cap is the floor of 1.20,
    which is 1, so the bucket admits exactly one hull — and the bucket-less hull
    parked in the same zone is not one of the rows counted.

    The membership of the stored hull is what PRD.md section 2.8 declares for
    `FinishedUnit`: "`demand_bucket_id` (default null, copied from the producing
    order at storage time".

    That the two refusals did not spend the warehouse version is not incidental
    either. PRD.md section 2.6: "These guards are evaluated late — after
    authorization, after existence, after schema, after every state and capacity
    rule the endpoint declares — so a request that is both stale and otherwise
    invalid reports the other failure, not the stale-version failure", and PRD.md
    section 2.10: "when any validation the triggering request declares fails,
    nothing at all is persisted ... no version increment."

    Design: Corner/validations/val_conditional_build_ahead_rungs_apply_only_to_bucket_bearing_orders
    """
    ctx = setup_sellable_units(
        unit_count=1,
        model_overrides=dict(_P6_ROUND_CUBE_MODEL),
        warehouse_overrides={
            "footprint_capacity_cube_m3": 100.0,
            "zones": [zone(DEFAULT_ZONE_CODE, 100.0)],
        },
        order_overrides={"ordered_qty": 2},
    )
    site_id = ctx["warehouse_id"]
    bucket_free_hull = ctx["sellable_units"][0]
    assert bucket_free_hull["logistics_status"] == "UNALLOCATED"
    assert ctx["production_order"]["demand_bucket_id"] is None

    # A season whose window has not opened at the clock's date, and whose cap
    # admits exactly one hull.
    bucket = create_demand_bucket(
        ctx,
        forecast_qty=2,
        build_ahead_cap_pct=60.0,
        window_start_on="2026-09-01",
        window_end_on="2026-09-30",
    )
    assert bucket["build_ahead_cap_qty"] == 1
    assert bucket["build_ahead_committed_qty"] == 0

    bucket_order = create_production_order(ctx, ordered_qty=2, demand_bucket_id=bucket["id"])
    assert bucket_order["demand_bucket_id"] == bucket["id"]
    bucket_hulls = _p6_second_cycle_of_hulls(
        ctx,
        bucket_order,
        oven_start_at="2026-08-01T11:00:00Z",
        oven_end_at="2026-08-01T12:00:00Z",
        cooling_end_at="2026-08-01T12:35:00Z",
    )
    assert len(bucket_hulls) == 2
    assert [hull["build_status"] for hull in bucket_hulls] == ["SELLABLE", "SELLABLE"]

    # Out of window: the bucket-bearing hull is refused.
    version_before = warehouse_version(site_id)
    too_early = api.store_finished_unit(
        bucket_hulls[0]["id"], store_payload(version_before), planner_headers
    )
    validate_error(too_early, ApiErrorId.BUILD_AHEAD_WINDOW_MISMATCH, 409)

    # Same instant, same model, same site, same warehouse version — and no bucket.
    plain = validate_success(
        api.store_finished_unit(
            bucket_free_hull["id"], store_payload(version_before), planner_headers
        )
    )
    assert plain["logistics_status"] == "STORED"
    assert plain["is_zone_anchor"] is True
    assert plain["storage_zone_code"] == DEFAULT_ZONE_CODE
    assert plain["demand_bucket_id"] is None
    assert_decimal_equals(
        plain["stored_footprint_cube_m3"], 1.0, Q_CUBE, "stored_footprint_cube_m3"
    )
    unmoved = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert unmoved["build_ahead_committed_qty"] == 0, (
        "a bucket-less hull is never a member of the counted set"
    )

    # One second before the inclusive first date is still outside the window.
    set_clock("2026-08-31T23:59:59Z")
    version_before_the_window = warehouse_version(site_id)
    one_second_early = api.store_finished_unit(
        bucket_hulls[0]["id"], store_payload(version_before_the_window), planner_headers
    )
    validate_error(one_second_early, ApiErrorId.BUILD_AHEAD_WINDOW_MISMATCH, 409)

    # At the window's first instant the byte-identical store is admitted, on the
    # warehouse version the two refusals did not consume.
    set_clock("2026-09-01T00:00:00Z")
    admitted = validate_success(
        api.store_finished_unit(
            bucket_hulls[0]["id"], store_payload(version_before_the_window), planner_headers
        )
    )
    assert admitted["logistics_status"] == "STORED"
    assert admitted["storage_zone_code"] == DEFAULT_ZONE_CODE
    assert admitted["is_zone_anchor"] is False
    assert admitted["demand_bucket_id"] == bucket["id"]
    assert_instant_equals(admitted["stored_at"], "2026-09-01T00:00:00Z", "stored_at")
    assert_decimal_equals(
        admitted["stored_footprint_cube_m3"], 0.5, Q_CUBE, "stored_footprint_cube_m3"
    )

    # Inside the window the quota finally applies, and it is already met.
    on_the_cap = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert on_the_cap["build_ahead_cap_qty"] == 1
    assert on_the_cap["build_ahead_committed_qty"] == 1
    version_before_the_cap = warehouse_version(site_id)
    over_the_cap = api.store_finished_unit(
        bucket_hulls[1]["id"], store_payload(version_before_the_cap), planner_headers
    )
    validate_error(over_the_cap, ApiErrorId.BUILD_AHEAD_CAP_EXCEEDED, 409)

    closed = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert closed["build_ahead_cap_qty"] == 1
    assert closed["build_ahead_committed_qty"] == 1
    assert warehouse_version(site_id) == version_before_the_cap
    turned_away = api.read_entity(
        "get_finished_unit", bucket_hulls[1]["id"], planner_headers
    )
    assert turned_away["logistics_status"] == "UNALLOCATED"
    assert turned_away["warehouse_id"] is None
    assert turned_away["storage_zone_code"] is None
    assert_decimal_equals(
        turned_away["stored_footprint_cube_m3"], 0.0, Q_CUBE, "stored_footprint_cube_m3"
    )

    # Two hulls of the same model share one zone; only one of them is the bucket's.
    summary = api.read_footprint_summary(site_id, planner_headers)
    assert_footprint_summary_consistent(summary)
    assert_decimal_equals(summary["committed_cube_m3"], 1.5, Q_CUBE, "committed_cube_m3")
    assert len(summary["zones"]) == 1
    assert summary["zones"][0]["stored_unit_count"] == 2
    assert_decimal_equals(
        summary["zones"][0]["remaining_cube_m3"], 98.5, Q_CUBE, "remaining_cube_m3"
    )


def test_the_deformation_threshold_binds_only_on_hull_deformation_claims(
    api, warranty_agent_headers
):
    """3.00 mm is claimable, 2.99 is not, and neither number binds a `COSMETIC` claim.

    PRD.md section 3.9: "A deformation claim must be substantiated: for
    `claim_type` `HULL_DEFORMATION` the `reported_deformation_mm` must be at or
    above the deformation threshold of 3.00 millimetres, otherwise
    `ERR_DEFORMATION_BELOW_THRESHOLD` (HTTP 422); exactly 3.00 is accepted and the
    threshold is not applied to the other two claim types."  The gate is keyed on
    `claim_type`, not on whether the field was supplied, so the `COSMETIC` claim
    carrying 1.00 mm and the `HARDWARE` claim carrying 2.00 mm must both be
    accepted — an implementation that checked the number whenever it was present
    would refuse them.

    The missing reading is a violation rather than a schema error because the same
    section makes the field optional and gives it a value: the body carries "an
    optional `reported_deformation_mm` at two decimals defaulting to 0.00".  A
    `HULL_DEFORMATION` claim that reports nothing therefore reports 0.00, which is
    below 3.00.

    Uniqueness is a separate check with its own code, and the replayed
    `claim_code` here clears the threshold at 5.00 mm so that only one defect
    remains: PRD.md section 3.9 says the body carries "a globally unique
    `claim_code` of 3 to 32 characters (`ERR_DUPLICATE_CODE`, HTTP 409)".

    Every accepted claim is asserted to be pre-pricing, per PRD.md section 3.9: "A
    new claim starts with `claim_status` `SUBMITTED`, `storage_review_status`
    `NOT_STARTED`, `months_in_service` null and every money field —
    `payout_basis`, `pre_fee_gross_cents`, `storage_deduction_cents`,
    `admin_fee_cents`, `net_payout_cents` — and `denial_reason` null, with
    `version` 1."

    Design: Corner/validations/val_conditional_deformation_threshold_applies_only_to_hull_deformation_claims
    """
    ctx = setup_delivered_unit_with_customer()
    customer_id = ctx["customer_id"]
    first_hull, second_hull = ctx["delivered_units"][0], ctx["delivered_units"][1]
    assert first_hull["logistics_status"] == "DELIVERED"
    assert second_hull["logistics_status"] == "DELIVERED"

    # Well after delivery, so the hulls are in service and every claim below
    # differs from its neighbour in one field only.
    set_clock("2027-03-01T12:00:00Z")

    below = api.create_warranty_claim(
        warranty_claim_payload(
            first_hull["id"],
            customer_id,
            claim_type="HULL_DEFORMATION",
            reported_deformation_mm=2.99,
        ),
        warranty_agent_headers,
    )
    validate_error(below, ApiErrorId.DEFORMATION_BELOW_THRESHOLD, 422)

    at_the_threshold = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                first_hull["id"],
                customer_id,
                claim_type="HULL_DEFORMATION",
                reported_deformation_mm=3.0,
            ),
            warranty_agent_headers,
        ),
        201,
    )
    assert_decimal_equals(
        at_the_threshold["reported_deformation_mm"], 3.0, _P6_Q_MM, "reported_deformation_mm"
    )

    # A COSMETIC claim that reports nothing at all.
    unmeasured_cosmetic = warranty_claim_payload(
        first_hull["id"], customer_id, claim_type="COSMETIC"
    )
    del unmeasured_cosmetic["reported_deformation_mm"]
    cosmetic_silent = validate_success(
        api.create_warranty_claim(unmeasured_cosmetic, warranty_agent_headers), 201
    )
    assert cosmetic_silent["claim_type"] == "COSMETIC"
    assert_decimal_equals(
        cosmetic_silent["reported_deformation_mm"], 0.0, _P6_Q_MM, "reported_deformation_mm"
    )

    # A COSMETIC claim that does report a reading, far below the threshold.
    cosmetic_measured = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                second_hull["id"],
                customer_id,
                claim_type="COSMETIC",
                reported_deformation_mm=1.0,
            ),
            warranty_agent_headers,
        ),
        201,
    )
    assert_decimal_equals(
        cosmetic_measured["reported_deformation_mm"], 1.0, _P6_Q_MM, "reported_deformation_mm"
    )

    # And a HARDWARE claim, which pins the exemption to more than one claim type.
    hardware = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                second_hull["id"],
                customer_id,
                claim_type="HARDWARE",
                reported_deformation_mm=2.0,
            ),
            warranty_agent_headers,
        ),
        201,
    )
    assert_decimal_equals(
        hardware["reported_deformation_mm"], 2.0, _P6_Q_MM, "reported_deformation_mm"
    )

    # A HULL_DEFORMATION claim with no reading at all: the default 0.00 is below
    # the threshold, so absence is a violation and not a schema complaint.
    unmeasured_deformation = warranty_claim_payload(
        second_hull["id"], customer_id, claim_type="HULL_DEFORMATION"
    )
    del unmeasured_deformation["reported_deformation_mm"]
    silent_deformation = api.create_warranty_claim(
        unmeasured_deformation, warranty_agent_headers
    )
    validate_error(silent_deformation, ApiErrorId.DEFORMATION_BELOW_THRESHOLD, 422)

    # The duplicate code clears the threshold at 5.00 mm, so the 409 is the code.
    replayed_code = api.create_warranty_claim(
        warranty_claim_payload(
            second_hull["id"],
            customer_id,
            claim_code=at_the_threshold["claim_code"],
            claim_type="HULL_DEFORMATION",
            reported_deformation_mm=5.0,
        ),
        warranty_agent_headers,
    )
    validate_error(replayed_code, ApiErrorId.DUPLICATE_CODE, 409)

    # Four accepted, three refused, and the refused ones left no row: the 2.99 mm
    # code and the unmeasured code are both still free.
    rows, meta = validate_paginated(
        api.list_warranty_claims({"customer_id": customer_id}, warranty_agent_headers)
    )
    assert meta["total_count"] == 4
    assert sorted(row["claim_code"] for row in rows) == sorted(
        [
            at_the_threshold["claim_code"],
            cosmetic_silent["claim_code"],
            cosmetic_measured["claim_code"],
            hardware["claim_code"],
        ]
    )
    assert sorted(row["claim_type"] for row in rows) == [
        "COSMETIC",
        "COSMETIC",
        "HARDWARE",
        "HULL_DEFORMATION",
    ]
    for row in rows:
        assert row["claim_status"] == "SUBMITTED", row["claim_code"]
        assert row["storage_review_status"] == "NOT_STARTED", row["claim_code"]
        assert row["version"] == 1, row["claim_code"]
        assert row["payout_basis"] is None, row["claim_code"]
        assert row["pre_fee_gross_cents"] is None, row["claim_code"]
        assert row["storage_deduction_cents"] is None, row["claim_code"]
        assert row["admin_fee_cents"] is None, row["claim_code"]
        assert row["net_payout_cents"] is None, row["claim_code"]
        assert row["denial_reason"] is None, row["claim_code"]
        # PRD.md section 3.9 calls a new claim's months_in_service null while the
        # section 2.8 field reference gives it a default of 0; either reading is
        # pre-pricing, and only the freezing done by a review may raise it.
        assert row["months_in_service"] in (None, 0), row["claim_code"]


def test_no_eligible_zone_answers_even_where_the_site_total_would_have_admitted_the_hull(
    api, planner_headers
):
    """A site with 1.2000 m3 free refuses a 1.0000 m3 hull, because no zone holds it.

    PRD.md section 3.7 orders the store gates: "Third, an eligible zone must exist,
    otherwise `ERR_NO_ELIGIBLE_ZONE` (HTTP 409). Fourth, the bucket's quota and
    then the site's total cube must both hold."  The same section keeps the two
    cube tests apart in as many words: "Separately, the site's total committed cube
    after a store must not exceed `footprint_capacity_cube_m3`, at-or-equal being
    accepted, otherwise `ERR_WAREHOUSE_CUBE_EXCEEDED` (HTTP 409). That site-total
    check is distinct from the per-zone fit failure `ERR_NO_ELIGIBLE_ZONE`."  The
    first store below satisfies the site total outright — 0.0000 plus 1.0000 is
    inside 1.2000 — and is still refused, so a site aggregate is never a substitute
    for a zone that fits.

    The per-zone arithmetic is PRD.md section 3.7's: "the candidate footprint is
    the model's `gross_cube_m3` multiplied by its `nest_factor` and rounded to four
    decimals when an anchor exists, and simply `gross_cube_m3` rounded to four
    decimals when none does; the zone's committed cube is the rounded sum of
    `stored_footprint_cube_m3` over its occupying hulls; and the remaining cube
    after admission is the zone's `capacity_cube_m3` minus that committed sum minus
    the candidate footprint, rounded to four decimals. A zone is eligible when that
    remainder is at or above 0.0000, so a zone that fills to exactly capacity is
    eligible. Eligible zones are ranked with anchor affinity first (zones already
    anchoring this hull model win), then tightest fit by ascending remaining cube,
    then ascending `zone_code`".  Two empty 0.6000 zones therefore both compute
    minus 0.4000 and neither is eligible, while at the second site the two stores
    land at exactly 0.0000 twice: the first opens a group in `Z1`, and the second
    cannot join it — `Z1` would compute 1.0000 minus 1.0000 minus 0.5000 — so
    affinity loses to eligibility and `Z2` becomes a second anchor at full cube.

    The consequence of filling a site to the last cubic metre is PRD.md
    section 3.7's derived posture: "`posture` is `FROZEN` when `utilization_pct` is
    at or above `frozen_threshold_pct`".

    Design: Corner/validations/val_cascading_zone_eligibility_resolves_before_the_site_cube_aggregate
    """
    ctx = setup_sellable_units(
        unit_count=1,
        model_overrides=dict(_P6_ROUND_CUBE_MODEL),
        warehouse_overrides={
            "footprint_capacity_cube_m3": 1.2,
            "zones": [zone("Z1", 0.6), zone("Z2", 0.6)],
        },
        order_overrides={"ordered_qty": 2},
    )
    split_site_id = ctx["warehouse_id"]
    tight_hull = ctx["sellable_units"][0]

    # A second site of the same shape but roomier zones, and hulls of its own.
    roomy_site = validate_success(
        api.create_warehouse(
            warehouse_payload(
                footprint_capacity_cube_m3=2.0, zones=[zone("Z1", 1.0), zone("Z2", 1.0)]
            ),
            planner_headers,
        ),
        201,
    )
    roomy_order = create_production_order(
        ctx, ordered_qty=2, target_warehouse_id=roomy_site["id"]
    )
    assert roomy_order["target_warehouse_id"] == roomy_site["id"]
    roomy_hulls = _p6_second_cycle_of_hulls(
        ctx,
        roomy_order,
        oven_start_at="2026-08-01T11:00:00Z",
        oven_end_at="2026-08-01T12:00:00Z",
        cooling_end_at="2026-08-01T12:35:00Z",
    )
    assert len(roomy_hulls) == 2

    # The split site has more free cube than the hull needs, in no single zone.
    before = api.read_footprint_summary(split_site_id, planner_headers)
    assert_footprint_summary_consistent(before)
    assert_decimal_equals(before["committed_cube_m3"], 0.0, Q_CUBE, "committed_cube_m3")
    assert_decimal_equals(before["remaining_cube_m3"], 1.2, Q_CUBE, "remaining_cube_m3")
    zones_before = {row["zone_code"]: row for row in before["zones"]}
    assert sorted(zones_before) == ["Z1", "Z2"]
    for code in ("Z1", "Z2"):
        assert_decimal_equals(
            zones_before[code]["committed_cube_m3"], 0.0, Q_CUBE, f"{code} committed"
        )
        assert_decimal_equals(
            zones_before[code]["remaining_cube_m3"], 0.6, Q_CUBE, f"{code} remaining"
        )
        assert zones_before[code]["anchor_product_model_ids"] == []
        assert zones_before[code]["stored_unit_count"] == 0

    version_before = warehouse_version(split_site_id)
    refused = api.store_finished_unit(
        tight_hull["id"], store_payload(version_before), planner_headers
    )
    validate_error(refused, ApiErrorId.NO_ELIGIBLE_ZONE, 409)

    # At the roomier site the eligibility bound is met at equality, twice.
    anchor = validate_success(
        api.store_finished_unit(
            roomy_hulls[0]["id"],
            store_payload(warehouse_version(roomy_site["id"])),
            planner_headers,
        )
    )
    assert anchor["storage_zone_code"] == "Z1", "empty zones tie, and zone_code ASC decides"
    assert anchor["is_zone_anchor"] is True
    assert anchor["logistics_status"] == "STORED"
    assert_decimal_equals(
        anchor["stored_footprint_cube_m3"], 1.0, Q_CUBE, "stored_footprint_cube_m3"
    )

    second_anchor = validate_success(
        api.store_finished_unit(
            roomy_hulls[1]["id"],
            store_payload(warehouse_version(roomy_site["id"])),
            planner_headers,
        )
    )
    assert second_anchor["storage_zone_code"] == "Z2", (
        "Z1 anchors this model but cannot fit a nested sibling, so affinity loses"
    )
    assert second_anchor["is_zone_anchor"] is True
    assert_decimal_equals(
        second_anchor["stored_footprint_cube_m3"], 1.0, Q_CUBE, "stored_footprint_cube_m3"
    )

    filled = api.read_footprint_summary(roomy_site["id"], planner_headers)
    assert_footprint_summary_consistent(filled)
    assert_decimal_equals(filled["committed_cube_m3"], 2.0, Q_CUBE, "committed_cube_m3")
    assert_decimal_equals(filled["remaining_cube_m3"], 0.0, Q_CUBE, "remaining_cube_m3")
    assert_decimal_equals(filled["utilization_pct"], 100.0, Q_PERCENT, "utilization_pct")
    assert filled["posture"] == "FROZEN"
    filled_zones = {row["zone_code"]: row for row in filled["zones"]}
    for code in ("Z1", "Z2"):
        assert_decimal_equals(
            filled_zones[code]["committed_cube_m3"], 1.0, Q_CUBE, f"{code} committed"
        )
        assert_decimal_equals(
            filled_zones[code]["remaining_cube_m3"], 0.0, Q_CUBE, f"{code} remaining"
        )
        assert filled_zones[code]["stored_unit_count"] == 1
        assert filled_zones[code]["anchor_product_model_ids"] == [ctx["product_model_id"]]

    roomy_now = api.read_entity("get_warehouse", roomy_site["id"], planner_headers)
    assert roomy_now["posture"] == "FROZEN"
    assert_decimal_equals(roomy_now["utilization_pct"], 100.0, Q_PERCENT, "utilization_pct")

    # The refused store wrote nothing: the split site is still empty and the hull
    # is still unallocated on the version it was refused against.
    assert warehouse_version(split_site_id) == version_before
    after = api.read_footprint_summary(split_site_id, planner_headers)
    assert_footprint_summary_consistent(after)
    assert_decimal_equals(after["committed_cube_m3"], 0.0, Q_CUBE, "committed_cube_m3")
    assert all(row["stored_unit_count"] == 0 for row in after["zones"])
    assert all(row["anchor_product_model_ids"] == [] for row in after["zones"])
    homeless = api.read_entity("get_finished_unit", tight_hull["id"], planner_headers)
    assert homeless["logistics_status"] == "UNALLOCATED"
    assert homeless["warehouse_id"] is None
    assert homeless["storage_zone_code"] is None
    assert homeless["is_zone_anchor"] is False
    assert_decimal_equals(
        homeless["stored_footprint_cube_m3"], 0.0, Q_CUBE, "stored_footprint_cube_m3"
    )
