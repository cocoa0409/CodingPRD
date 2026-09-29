"""Cross-cutting behaviour: version accounting, cascade fan-out and dual variants.

PRD.md §2.4 makes `version` advance by exactly 1 per persisted mutation, PRD.md
§2.6 hangs five concurrency guards off those numbers, and §3.2 through §3.9 hang
cascades off single writes. These tests audit the layers rather than one
endpoint: that a fan-out is still one version bump, that a refused write is zero,
that one call lands every consequence it declares, and that the oven-arm check
really is two different calculations depending on whether the arm is shared.
"""

from test_helpers import (
    ApiErrorId,
    Q_MASS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_money_equals,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    demold_payload,
    get_success_data,
    mold_payload,
    molding_cycle_payload,
    production_order_version,
    quarantine_payload,
    release_quarantine_payload,
    release_storage_payload,
    run_cycle_to_cooling,
    set_clock,
    setup_claim_under_review,
    setup_scheduled_cycle,
    setup_stored_units,
    shipment_line_payload,
    shipment_payload,
    suspend_payload,
    validate_error,
    validate_paginated,
    warranty_claim_payload,
)

CLOCK_START = "2026-08-01T00:00:00Z"


class TestVersionAccounting:
    """PRD §2.4 fixes the step size at exactly one, cascades included.

    PRD.md §2.4: "`version` is an integer that starts at 1 when the row is
    created and increments by exactly 1 on every persisted mutation, including
    mutations that occur as cascade side effects of a request aimed at a
    different resource."
    """

    def test_every_occ_parent_moves_by_one_per_write_and_by_zero_when_refused(
        self, api, admin_headers, planner_headers
    ):
        """All five concurrency parents are audited in one run, including a
        release-storage refused by the role gate.

        PRD.md §2.8: a hull model's amendable fields include `min_cooling_minutes`,
        and "Amending them ... the model's `version` advances by 1."
        PRD.md §3.7: releasing storage is "the head of **CASCADE-C**" and "both the
        site's and the hull's `version` advance by 1."
        PRD.md §5: `POST /finished-units/{finished_unit_id}/release-storage` is
        permitted to `LogisticsPlanner`.
        PRD.md §3.2: quarantine "is the head of **CASCADE-F** ... The lot's
        `version` advances by 1", and "Releasing a quarantine ... requires `status`
        `QUARANTINED`; the lot returns to `AVAILABLE` when `available_kg` is
        strictly greater than 0.000".
        PRD.md §3.8: "A new shipment starts in `PLANNED`", and adding a line
        "requires `expected_shipment_version`".
        PRD.md §3.3: an order "starts in `DRAFT` ... and `version` 1", and on
        release "the order moves `DRAFT` to `READY_TO_SCHEDULE` ... and `version`
        advances by 1."

        Design: Corner/cross_cutting_complexity_layers/layer_optimistic_concurrency_every_parent_version_moves_by_exactly_one_per_write
        """
        set_clock(CLOCK_START)
        ctx = setup_stored_units()
        model_id = ctx["product_model_id"]
        warehouse_id = ctx["warehouse_id"]
        lot_id = ctx["resin_lot_id"]
        anchor, follower = ctx["stored_units"][0], ctx["stored_units"][1]

        # Parent 1 — ProductModel, amended directly.
        model_before = api.read_version("get_product_model", model_id, admin_headers)
        patched = get_success_data(
            api.update_product_model(
                model_id, {"min_cooling_minutes": 31}, admin_headers
            )
        )
        assert patched["min_cooling_minutes"] == 31
        assert patched["version"] == model_before + 1

        # Parent 2 — Warehouse, moved by a cascade rather than by a direct write.
        site_before = api.read_version("get_warehouse", warehouse_id, planner_headers)
        get_success_data(
            api.release_storage(
                anchor["id"],
                release_storage_payload("seasonal reallocation"),
                planner_headers,
            )
        )
        site_after = api.read_version("get_warehouse", warehouse_id, planner_headers)
        assert site_after == site_before + 1, "CASCADE-C is still one write"

        # A refusal consumes nothing: release-storage is the planner's alone.
        validate_error(
            api.release_storage(
                follower["id"],
                release_storage_payload("seasonal reallocation"),
                ctx["assembly_headers"],
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
        )
        assert (
            api.read_version("get_warehouse", warehouse_id, planner_headers)
            == site_after
        )
        assert (
            api.read_entity("get_finished_unit", anchor["id"], planner_headers)[
                "logistics_status"
            ]
            == "UNALLOCATED"
        )
        assert (
            api.read_entity("get_finished_unit", follower["id"], planner_headers)[
                "logistics_status"
            ]
            == "STORED"
        )

        # Parent 3 — ResinLot, over the quarantine and its release.
        lot_before = api.read_version("get_resin_lot", lot_id, admin_headers)
        quarantined = get_success_data(
            api.quarantine_resin_lot(
                lot_id, quarantine_payload(), ctx["inspector_headers"]
            )
        )
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["version"] == lot_before + 1
        cleared = get_success_data(
            api.release_resin_lot_quarantine(
                lot_id, release_quarantine_payload(), ctx["inspector_headers"]
            )
        )
        assert cleared["status"] == "AVAILABLE"
        assert cleared["version"] == lot_before + 2

        # Parent 4 — Shipment, whose line write is guarded by its own version.
        trailer = get_success_data(
            api.create_shipment(shipment_payload(warehouse_id), planner_headers)
        )
        assert trailer["status"] == "PLANNED"
        assert trailer["version"] == 1
        get_success_data(
            api.create_shipment_line(
                shipment_line_payload(trailer["id"], follower["id"], 1),
                planner_headers,
            )
        )
        assert api.read_version("get_shipment", trailer["id"], planner_headers) == 2

        # Parent 5 — ProductionOrder, from DRAFT through its release edge.
        draft = create_production_order(ctx, release=False)
        assert draft["status"] == "DRAFT"
        assert draft["version"] == 1
        released = get_success_data(
            api.release_production_order(draft["id"], planner_headers)
        )
        assert released["status"] == "READY_TO_SCHEDULE"
        assert released["version"] == 2


class TestCascadeFanOut:
    """PRD §2.5 and §3.2-§3.9 hang whole fan-outs off single calls."""

    def test_suspending_a_customer_voids_the_open_claim_and_moves_no_money(
        self, api, admin_headers, warranty_agent_headers
    ):
        """The void is a side effect: it is visible on the next read, it spends
        nothing, and reinstatement does not undo it.

        PRD.md §3.6: "Suspending a customer requires a `suspend_reason` and
        `status` `ACTIVE` ... the suspension voids that customer's open warranty
        claims, moving every claim in `claim_status` `SUBMITTED` or `UNDER_REVIEW`
        to `VOIDED` with `denial_reason` `APPROVAL_VOIDED`. No money moves on
        those voids, because no payout had been booked. Reinstatement requires
        `status` `SUSPENDED` ... and it does *not* resurrect a voided claim."
        PRD.md §3.9: "A new claim starts with `claim_status` `SUBMITTED`,
        `storage_review_status` `NOT_STARTED` ..." and claims "may be listed and
        filtered by `finished_unit_id`, `customer_id` ..."
        PRD.md §2.4: `version` "increments by exactly 1 on every persisted
        mutation, including mutations that occur as cascade side effects".

        Design: Corner/cross_cutting_complexity_layers/layer_cascading_side_effects_customer_suspension_voids_open_claims_without_moving_the_reserve
        """
        set_clock(CLOCK_START)
        ctx = setup_claim_under_review()
        customer_id = ctx["customer_id"]
        model_id = ctx["product_model_id"]
        claim_id = ctx["warranty_claim_id"]

        model_before = api.read_entity("get_product_model", model_id, admin_headers)
        assert_money_equals(
            model_before["warranty_reserve_cents"], 500000, "reserve before suspension"
        )
        customer_before = api.read_version("get_customer", customer_id, admin_headers)

        suspended = get_success_data(
            api.suspend_customer(customer_id, suspend_payload("credit hold"), admin_headers)
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == customer_before + 1, "one write, one bump"

        voided = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
        assert voided["claim_status"] == "VOIDED", "the cascade needs no further call"
        assert voided["denial_reason"] == "APPROVAL_VOIDED"

        model_after = api.read_entity("get_product_model", model_id, admin_headers)
        assert_money_equals(
            model_after["warranty_reserve_cents"], 500000, "reserve after the void"
        )
        assert_money_equals(model_after["warranty_paid_cents"], 0, "warranty_paid_cents")

        reinstated = get_success_data(api.reinstate_customer(customer_id, admin_headers))
        assert reinstated["status"] == "ACTIVE"
        still_voided = api.read_entity(
            "get_warranty_claim", claim_id, warranty_agent_headers
        )
        assert still_voided["claim_status"] == "VOIDED", "not a resurrection"
        assert still_voided["denial_reason"] == "APPROVAL_VOIDED"

        second_hull = ctx["delivered_units"][1]
        fresh = get_success_data(
            api.create_warranty_claim(
                warranty_claim_payload(
                    second_hull["id"], customer_id, claim_code="CLM-CD-L2"
                ),
                warranty_agent_headers,
            )
        )
        assert fresh["claim_status"] == "SUBMITTED"
        assert fresh["storage_review_status"] == "NOT_STARTED"

        rows, meta = validate_paginated(
            api.list_warranty_claims({"customer_id": customer_id}, warranty_agent_headers)
        )
        assert meta["total_count"] == 2, "the voided claim is retained"
        assert {row["claim_status"] for row in rows} == {"VOIDED", "SUBMITTED"}

    def test_one_demold_call_lands_every_consequence_it_declares(
        self, api, admin_headers, planner_headers
    ):
        """Demoulding mints the hulls, wears the tool, leaves the resin ledger
        alone and re-rolls the order — all from one request.

        PRD.md §3.5: "**Demoulding** supplies `actual_cooling_end_at` ... The
        cycle moves `COOLING` to `DEMOLDED`, `actual_cooling_end_at` is recorded
        and `actual_cooling_minutes` recomputed by flooring ... The tool moves
        `IN_CYCLE` to `AVAILABLE` and its `cycles_since_service` is incremented by
        1 ... One hull is then minted per cavity."
        PRD.md §3.5: "Each new hull starts with `build_status` `DEMOLDED`,
        `logistics_status` `UNALLOCATED`, `inspection_verdict` `PENDING` and
        `rework_count` 0", with `hull_serial` "deterministic and uses no random
        value".
        PRD.md §2.8: a hull's `warehouse_id` is "default null, non-null only while
        the hull is stored, loaded or in transit" and `is_zone_anchor` is "boolean,
        default false".
        PRD.md §3.5: at oven start "Every `RESERVED` charge on the cycle becomes
        `CONSUMED`, moving `charge_kg` from its lot's `reserved_kg` to its lot's
        `consumed_kg` while `available_kg` is untouched".
        PRD.md §3.4: "**Order cost** is recomputed at oven start ..., at demould,
        and on every inspection that changes `completed_qty`."
        PRD.md §3.4: "`completed_qty` counts hulls whose `build_status` is
        `SELLABLE` **or** whose `logistics_status` is one of `STORED`, `LOADED`,
        `IN_TRANSIT` or `DELIVERED` ... Hulls in `DEMOLDED`, `TRIMMED`,
        `OUTFITTED` or `REWORK` count toward neither figure."

        Design: Corner/cross_cutting_complexity_layers/layer_cascading_side_effects_one_demold_call_fans_out_to_six_observable_facts
        """
        set_clock(CLOCK_START)
        ctx = setup_scheduled_cycle()
        run_cycle_to_cooling(ctx)
        cycle_id = ctx["molding_cycle_id"]
        mold_id = ctx["mold_id"]
        order_id = ctx["production_order_id"]

        mold_before = api.read_entity("get_mold", mold_id, admin_headers)
        assert mold_before["cycles_since_service"] == 0
        assert mold_before["status"] == "IN_CYCLE"

        set_clock("2026-08-01T10:35:00Z")
        demolded = get_success_data(
            api.demold(
                cycle_id,
                demold_payload("2026-08-01T10:35:00Z"),
                ctx["operator_headers"],
            )
        )
        assert demolded["status"] == "DEMOLDED"
        assert_instant_equals(
            demolded["actual_cooling_end_at"],
            "2026-08-01T10:35:00Z",
            "actual_cooling_end_at",
        )
        assert demolded["scheduled_cooling_minutes"] == 30
        assert demolded["actual_cooling_minutes"] == 35, "35 minutes clears the floor"

        hulls, meta = validate_paginated(
            api.list_finished_units({"molding_cycle_id": cycle_id}, planner_headers)
        )
        assert meta["total_count"] == 2, "one hull per cavity"
        for hull in hulls:
            assert hull["build_status"] == "DEMOLDED"
            assert hull["logistics_status"] == "UNALLOCATED"
            assert hull["product_model_id"] == ctx["product_model_id"]
            assert hull["hull_serial"], "the serial is minted by the cascade"
            assert hull["warehouse_id"] is None, "the demould stores nothing"
            assert hull["is_zone_anchor"] is False

        mold_after = api.read_entity("get_mold", mold_id, admin_headers)
        assert mold_after["cycles_since_service"] == 1, "exactly one per demould"
        assert mold_after["status"] == "AVAILABLE"

        lot = api.read_entity("get_resin_lot", ctx["resin_lot_id"], admin_headers)
        assert_decimal_equals(lot["available_kg"], "476.000", Q_MASS, "available_kg")
        assert_decimal_equals(lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(lot["consumed_kg"], "24.000", Q_MASS, "consumed_kg")

        # PRD.md §3.5 names the rows a demould revises — "The cycle's and the
        # tool's `version` each advance by 1" — and the order is not among them,
        # while the roll-up sentence of §3.3 attaches no version claim to the
        # recomputation itself. Whether the re-rolled cost alone advances the
        # order is therefore unstated, so only the roll-up's own outputs are
        # asserted here.
        order_after = api.read_entity("get_production_order", order_id, planner_headers)
        assert order_after["status"] == "IN_PRODUCTION"
        assert order_after["completed_qty"] == 0, "a DEMOLDED hull is not sellable yet"


class TestDualVariantOvenWindow:
    """PRD §3.4 runs the arm overlap check two ways on one station."""

    def test_a_coincident_window_is_legal_on_another_arm_and_refused_on_the_same_arm(
        self, api, admin_headers, planner_headers
    ):
        """Two identical 09:00 windows coexist on arms 1 and 2; a third on arm 1
        is refused by the arm check before the mould pool or the quota can speak.

        PRD.md §3.4: "The arm check gathers cycles sharing both `oven_station_id`
        and `arm_index` in `status` `SCHEDULED` or `OVEN_RUNNING` ... a single
        overlap refuses the booking with `ERR_OVEN_WINDOW_CONFLICT` ... Cycles on
        a different `arm_index` of the same station never conflict."
        PRD.md §3.4 fixes the order: "Then the oven arm window, then the bay slot
        count, then the mould pool, then the overbuild ceiling, and last of all
        `expected_production_order_version`."
        PRD.md §3.4: "The order's `version` advances by 1 in every case. A refused
        booking writes nothing at all — no cycle row, no order version bump."
        PRD.md §2.8: `arm_index` is a "required integer, at least 1 and no greater
        than the station's `arm_count` or `ERR_VALIDATION`".

        Design: Corner/cross_cutting_complexity_layers/layer_dual_variant_calculation_oven_window_same_arm_versus_different_arm_same_station
        """
        set_clock(CLOCK_START)
        ctx = create_plant_baseline()
        create_resin_lot()
        second_mold = get_success_data(
            api.create_mold(mold_payload(ctx["product_model_id"]), admin_headers)
        )
        order = create_production_order(ctx, ordered_qty=4)
        order_id = order["id"]
        operator_headers = ctx["operator_headers"]

        def cycle_body(**overrides):
            return molding_cycle_payload(
                order_id,
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(order_id),
                **overrides,
            )

        first = get_success_data(
            api.create_molding_cycle(cycle_body(arm_index=1), operator_headers)
        )
        second = get_success_data(
            api.create_molding_cycle(cycle_body(arm_index=2), operator_headers)
        )
        for cycle, arm in ((first, 1), (second, 2)):
            assert cycle["status"] == "SCHEDULED"
            assert cycle["oven_station_id"] == ctx["oven_station_id"]
            assert cycle["arm_index"] == arm
            assert_instant_equals(
                cycle["oven_start_at"], "2026-08-01T09:00:00Z", "oven_start_at"
            )
        assert first["mold_id"] != second["mold_id"], "separated by tool as well as arm"
        assert {first["mold_id"], second["mold_id"]} == {
            ctx["mold_id"],
            second_mold["id"],
        }

        # A third identical window on arm 1: the overlap answers first, even
        # though both tools are busy and the 4-hull ceiling is already met.
        version_before = production_order_version(order_id)
        validate_error(
            api.create_molding_cycle(cycle_body(arm_index=1), operator_headers),
            ApiErrorId.OVEN_WINDOW_CONFLICT,
        )
        assert production_order_version(order_id) == version_before
        _, meta = validate_paginated(
            api.list_molding_cycles({"production_order_id": order_id}, planner_headers)
        )
        assert meta["total_count"] == 2, "a refused booking writes nothing at all"

        # A nonexistent arm is never treated as a free arm.
        validate_error(
            api.create_molding_cycle(
                cycle_body(arm_index=3, oven_start_at="2026-08-01T14:00:00Z"),
                operator_headers,
            ),
            ApiErrorId.VALIDATION,
        )
        assert production_order_version(order_id) == version_before
