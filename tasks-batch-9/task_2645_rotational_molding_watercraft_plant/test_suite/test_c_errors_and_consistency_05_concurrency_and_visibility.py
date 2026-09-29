"""The consistency model: five late version guards and immediate readback.

PRD.md §2.6 names five write paths that mutate a parent the path does not name,
and each one carries the parent's `version` in its body. These tests drive every
one of those guards from a legitimate request whose only defect is a stale
number, then retry the identical body against the refreshed number. PRD.md §2.4
makes the bump visible to the very next read, so nothing here waits, polls or
settles: there is no token, cursor, retry hint or lock handle anywhere in the
surface, and the last test proves a whole multi-row cascade is readable in the
request that follows it.
"""

import re

from test_helpers import (
    ApiErrorId,
    DEFAULT_ZONE_CODE,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    approve_claim_payload,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_money_equals,
    assert_warranty_reserve_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    get_success_data,
    mold_payload,
    molding_cycle_payload,
    product_model_version,
    production_order_version,
    release_storage_payload,
    resin_charge_payload,
    resin_lot_version,
    set_clock,
    setup_claim_storage_verified,
    setup_sellable_units,
    setup_stored_units,
    shipment_line_payload,
    shipment_payload,
    shipment_version,
    store_payload,
    validate_error,
    validate_paginated,
    warehouse_version,
)

CLOCK_START = "2026-08-01T00:00:00Z"

_HANDLE_WORDS = ("token", "cursor", "retry", "lock", "lease", "etag", "nonce")


def _p7_assert_no_concurrency_handles(response, label):
    """Assert a response offers no coordination handle of any kind.

    PRD.md §2.6 gives callers exactly one concurrency signal — HTTP 412 on a
    named parent `version` — so nothing may hand back a token, a cursor, a
    retry-after or a lock handle. test_helpers has no assertion for this, so the
    partition defines its own rather than editing the shared package.
    """
    for header in response.headers:
        assert header.lower() not in ("retry-after", "etag", "x-lock-token"), (
            f"{label} returned a coordination header {header}"
        )

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                # Match whole snake_case segments, not substrings: PRD.md §2.8
                # declares a ResinCharge field named `released_reason`, and a
                # bare substring test would read the "lease" inside "released"
                # as a coordination handle.
                segments = set(re.split(r"[^a-z0-9]+", key.lower()))
                for word in _HANDLE_WORDS:
                    assert word not in segments, (
                        f"{label} exposes '{path}.{key}', a coordination handle"
                    )
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(response.json(), label)


class TestCycleCreateConcurrency:
    """PRD §2.6: "Creating a moulding cycle requires
    `expected_production_order_version` ... A mismatch yields
    `ERR_STALE_PRODUCTION_ORDER_VERSION`."
    """

    def test_a_stale_order_version_is_refused_and_the_refreshed_number_succeeds(
        self, api, admin_headers, planner_headers
    ):
        """The second booking is valid in every other respect — free arm, free
        tool, quota headroom, free cooling slot — so only the version refuses it.

        PRD.md §2.6: "Creating a moulding cycle requires
        `expected_production_order_version`, compared against the `version` of the
        `ProductionOrder` named by `production_order_id`. A mismatch yields
        `ERR_STALE_PRODUCTION_ORDER_VERSION`", and on any mismatch "nothing is
        persisted — no child row is created, no ledger is moved, no cascade runs."
        PRD.md §2.6: "any earlier accepted write against the parent row ...
        invalidates a previously read version number and the caller must re-read
        the parent before retrying."
        PRD.md §3.4: "The order's `version` advances by 1 in every case. A refused
        booking writes nothing at all — no cycle row, no order version bump."
        PRD.md §3.4: "Cycles on a different `arm_index` of the same station never
        conflict."

        Design: Corner/consistency_model/occ_cycle_create_stale_order_version_then_the_refreshed_version_succeeds
        """
        set_clock(CLOCK_START)
        ctx = create_plant_baseline()
        create_resin_lot()
        second_mold = get_success_data(
            api.create_mold(mold_payload(ctx["product_model_id"]), admin_headers)
        )
        order = create_production_order(ctx, ordered_qty=4)
        order_id = order["id"]
        assert order["status"] == "READY_TO_SCHEDULE"

        version_a = production_order_version(order_id)
        body = molding_cycle_payload(
            order_id,
            ctx["oven_station_id"],
            ctx["cooling_bay_id"],
            version_a,
            arm_index=1,
        )
        first = get_success_data(
            api.create_molding_cycle(body, ctx["operator_headers"])
        )
        assert first["status"] == "SCHEDULED"
        assert first["arm_index"] == 1
        assert first["mold_id"] in (ctx["mold_id"], second_mold["id"])

        stale = dict(body, arm_index=2)
        refused = api.create_molding_cycle(stale, ctx["operator_headers"])
        validate_error(refused, ApiErrorId.STALE_PRODUCTION_ORDER_VERSION)
        _p7_assert_no_concurrency_handles(refused, "the stale cycle create")
        _, meta = validate_paginated(
            api.list_molding_cycles({"production_order_id": order_id}, planner_headers)
        )
        assert meta["total_count"] == 1, "the refusal created nothing"

        version_b = production_order_version(order_id)
        assert version_b == version_a + 1, "the bump is visible to the very next read"

        retried = api.create_molding_cycle(
            dict(stale, expected_production_order_version=version_b),
            ctx["operator_headers"],
        )
        second = get_success_data(retried)
        _p7_assert_no_concurrency_handles(retried, "the accepted cycle create")
        assert second["status"] == "SCHEDULED"
        assert second["arm_index"] == 2
        assert second["mold_id"] != first["mold_id"], "the request was always valid"
        assert production_order_version(order_id) == version_b + 1
        _, meta_after = validate_paginated(
            api.list_molding_cycles({"production_order_id": order_id}, planner_headers)
        )
        assert meta_after["total_count"] == 2


class TestChargeCreateConcurrency:
    """PRD §2.6: "Creating a resin charge requires `expected_resin_lot_version`
    ... A mismatch yields `ERR_STALE_RESIN_LOT_VERSION`."
    """

    def test_a_stale_lot_version_leaves_the_three_bucket_ledger_exactly_as_it_was(
        self, api, admin_headers, planner_headers
    ):
        """The refused reservation moves no mass at all, and the retry moves
        precisely one more shot.

        PRD.md §2.6: "Creating a resin charge requires
        `expected_resin_lot_version`, compared against the `version` of the
        `ResinLot` named by `resin_lot_id`. A mismatch yields
        `ERR_STALE_RESIN_LOT_VERSION`", and on a mismatch "nothing is persisted —
        no child row is created, no ledger is moved, no cascade runs."
        PRD.md §2.6: "These guards are evaluated late — after authorization, after
        existence, after schema, after every state and capacity rule the endpoint
        declares."
        PRD.md §2.8: a lot's "`received_kg` ... always equals the sum of
        `available_kg`, `reserved_kg` and `consumed_kg`."
        PRD.md §3.2: on reservation "`charge_kg` moves from the lot's
        `available_kg` to its `reserved_kg`."

        Design: Corner/consistency_model/occ_charge_create_stale_resin_lot_version_preserves_the_mass_ledger
        """
        set_clock(CLOCK_START)
        ctx = create_plant_baseline()
        lot = create_resin_lot()
        lot_id = lot["id"]
        get_success_data(
            api.create_mold(mold_payload(ctx["product_model_id"]), admin_headers)
        )
        order = create_production_order(ctx, ordered_qty=4)
        order_id = order["id"]

        def book(arm_index):
            return get_success_data(
                api.create_molding_cycle(
                    molding_cycle_payload(
                        order_id,
                        ctx["oven_station_id"],
                        ctx["cooling_bay_id"],
                        production_order_version(order_id),
                        arm_index=arm_index,
                    ),
                    ctx["operator_headers"],
                )
            )

        cycle_a = book(1)
        cycle_b = book(2)

        lot_version_a = resin_lot_version(lot_id)
        first = get_success_data(
            api.create_resin_charge(
                resin_charge_payload(cycle_a["id"], lot_id, lot_version_a),
                ctx["resin_tech_headers"],
            )
        )
        assert first["status"] == "RESERVED"
        assert_decimal_equals(first["charge_kg"], "24.000", Q_MASS, "charge_kg")

        stale_body = resin_charge_payload(cycle_b["id"], lot_id, lot_version_a)
        refused = api.create_resin_charge(stale_body, ctx["resin_tech_headers"])
        validate_error(refused, ApiErrorId.STALE_RESIN_LOT_VERSION)
        _p7_assert_no_concurrency_handles(refused, "the stale charge create")

        after_412 = api.read_entity("get_resin_lot", lot_id, admin_headers)
        assert_decimal_equals(after_412["available_kg"], "476.000", Q_MASS, "available_kg")
        assert_decimal_equals(after_412["reserved_kg"], "24.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(after_412["consumed_kg"], "0.000", Q_MASS, "consumed_kg")
        assert_decimal_equals(after_412["received_kg"], "500.000", Q_MASS, "received_kg")
        _, meta = validate_paginated(
            api.list_resin_charges({"molding_cycle_id": cycle_b["id"]}, admin_headers)
        )
        assert meta["total_count"] == 0, "the 412 created no charge row"

        lot_version_b = resin_lot_version(lot_id)
        assert lot_version_b == lot_version_a + 1
        retried = api.create_resin_charge(
            dict(stale_body, expected_resin_lot_version=lot_version_b),
            ctx["resin_tech_headers"],
        )
        second = get_success_data(retried)
        _p7_assert_no_concurrency_handles(retried, "the accepted charge create")
        assert second["status"] == "RESERVED"

        assert resin_lot_version(lot_id) == lot_version_b + 1
        final = api.read_entity("get_resin_lot", lot_id, admin_headers)
        assert_decimal_equals(final["available_kg"], "452.000", Q_MASS, "available_kg")
        assert_decimal_equals(final["reserved_kg"], "48.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(final["consumed_kg"], "0.000", Q_MASS, "consumed_kg")


class TestStoreConcurrency:
    """PRD §2.6: "Storing a finished unit requires `expected_warehouse_version`
    ... A mismatch yields `ERR_STALE_WAREHOUSE_VERSION`."
    """

    def test_a_stale_site_version_after_the_sibling_lands_then_the_retry_nests(
        self, api, planner_headers
    ):
        """The site has 20.0000 m3 free, so only the version the first store
        advanced can refuse the second — and the refreshed retry nests at half cube.

        PRD.md §2.6: "Storing a finished unit requires
        `expected_warehouse_version`, compared against the `version` of the
        destination `Warehouse`. A mismatch yields `ERR_STALE_WAREHOUSE_VERSION`",
        with "nothing is persisted" on a mismatch.
        PRD.md §3.7: "Opening a **new nest group** ... charges the full
        `gross_cube_m3` and sets `is_zone_anchor` true. **Joining an existing nest
        group** charges `gross_cube_m3` multiplied by `nest_factor` and leaves
        `is_zone_anchor` false."
        PRD.md §3.7: "the site's `committed_cube_m3` is recomputed as the rounded
        sum of `stored_footprint_cube_m3` over its hulls in `STORED` or `LOADED`",
        "`utilization_pct` is recomputed as `committed_cube_m3` divided by
        `footprint_capacity_cube_m3` times 100, rounded to two decimals, and
        `posture` is re-derived from it", and "Both the site's and the hull's
        `version` advance by 1."
        PRD.md §3.7: "`posture` is ... `NORMAL` otherwise."
        PRD.md §3.8: "The site footprint read returns the origin or any site's
        `committed_cube_m3`, `utilization_pct`, derived `posture`, remaining cube,
        and the per-zone breakdown."

        Design: Corner/consistency_model/occ_store_unit_stale_warehouse_version_after_the_sibling_hull_lands
        """
        set_clock(CLOCK_START)
        ctx = setup_sellable_units()
        warehouse_id = ctx["warehouse_id"]
        anchor, follower = ctx["sellable_units"][0], ctx["sellable_units"][1]

        site_version_a = warehouse_version(warehouse_id)
        stored = get_success_data(
            api.store_finished_unit(
                anchor["id"], store_payload(site_version_a), planner_headers
            )
        )
        assert stored["logistics_status"] == "STORED"
        assert stored["is_zone_anchor"] is True
        assert stored["storage_zone_code"] == DEFAULT_ZONE_CODE
        assert_decimal_equals(
            stored["stored_footprint_cube_m3"], "2.0000", Q_CUBE, "anchor footprint"
        )

        refused = api.store_finished_unit(
            follower["id"], store_payload(site_version_a), planner_headers
        )
        validate_error(refused, ApiErrorId.STALE_WAREHOUSE_VERSION)
        _p7_assert_no_concurrency_handles(refused, "the stale store")
        assert (
            api.read_entity("get_finished_unit", follower["id"], planner_headers)[
                "logistics_status"
            ]
            == "UNALLOCATED"
        )
        site_after_412 = api.read_entity("get_warehouse", warehouse_id, planner_headers)
        assert_decimal_equals(
            site_after_412["committed_cube_m3"], "2.0000", Q_CUBE, "committed_cube_m3"
        )

        site_version_b = warehouse_version(warehouse_id)
        assert site_version_b == site_version_a + 1
        retried = api.store_finished_unit(
            follower["id"], store_payload(site_version_b), planner_headers
        )
        nested = get_success_data(retried)
        _p7_assert_no_concurrency_handles(retried, "the accepted store")
        assert nested["is_zone_anchor"] is False
        assert_decimal_equals(
            nested["stored_footprint_cube_m3"], "1.0000", Q_CUBE, "nested footprint"
        )
        assert warehouse_version(warehouse_id) == site_version_b + 1

        summary = api.read_footprint_summary(warehouse_id, planner_headers)
        assert_footprint_summary_consistent(summary)
        assert_decimal_equals(
            summary["utilization_pct"], "15.00", Q_PERCENT, "utilization_pct"
        )
        assert summary["posture"] == "NORMAL"
        zone = next(z for z in summary["zones"] if z["zone_code"] == DEFAULT_ZONE_CODE)
        assert_decimal_equals(
            zone["committed_cube_m3"], "3.0000", Q_CUBE, "zone committed_cube_m3"
        )
        assert_decimal_equals(
            zone["remaining_cube_m3"], "17.0000", Q_CUBE, "zone remaining_cube_m3"
        )
        assert zone["anchor_product_model_ids"] == [ctx["product_model_id"]]


class TestLineCreateConcurrency:
    """PRD §2.6: "Creating a shipment line requires `expected_shipment_version`
    ... A mismatch yields `ERR_STALE_SHIPMENT_VERSION`."
    """

    def test_a_stale_trailer_version_refuses_before_the_nest_position_is_taken(
        self, api, planner_headers
    ):
        """A 10.0000 m3 / 100.000 kg trailer carrying 3.0000 m3 and 48.000 kg has
        no ceiling in play, so the version is the only possible refusal.

        PRD.md §2.6: "Creating a shipment line requires
        `expected_shipment_version`, compared against the `version` of the
        `Shipment` named by `shipment_id`. A mismatch yields
        `ERR_STALE_SHIPMENT_VERSION`", and on a mismatch "no child row is created".
        PRD.md §3.8: "a line's `nest_position` is one plus the number of earlier
        lines whose hull shares the same `product_model_id`"; "Its
        `line_nested_cube_m3` is the full gross cube when its `nest_position` is 1,
        and `gross_cube_m3` multiplied by `nest_factor`, rounded to four decimals,
        for every position after the first"; "`nested_cube_m3` the sum of the
        per-line nested cubes ... `loaded_weight_kg` is the sum of the hulls'
        `unit_weight_kg` rounded to three decimals".

        Design: Corner/consistency_model/occ_line_create_stale_shipment_version_before_the_nest_position_is_taken
        """
        set_clock(CLOCK_START)
        ctx = setup_stored_units()
        first_hull, second_hull = ctx["stored_units"][0], ctx["stored_units"][1]
        trailer = get_success_data(
            api.create_shipment(
                shipment_payload(
                    ctx["warehouse_id"],
                    trailer_cube_capacity_m3=10.0,
                    trailer_max_payload_kg=100.0,
                ),
                planner_headers,
            )
        )
        trailer_id = trailer["id"]

        version_a = shipment_version(trailer_id)
        first_line = get_success_data(
            api.create_shipment_line(
                shipment_line_payload(trailer_id, first_hull["id"], version_a),
                planner_headers,
            )
        )
        assert first_line["nest_position"] == 1
        assert_decimal_equals(
            first_line["line_nested_cube_m3"], "2.0000", Q_CUBE, "line_nested_cube_m3"
        )
        after_first = api.read_entity("get_shipment", trailer_id, planner_headers)
        assert_decimal_equals(
            after_first["nested_cube_m3"], "2.0000", Q_CUBE, "nested_cube_m3"
        )
        assert_decimal_equals(
            after_first["loaded_weight_kg"], "24.000", Q_MASS, "loaded_weight_kg"
        )

        stale_body = shipment_line_payload(trailer_id, second_hull["id"], version_a)
        refused = api.create_shipment_line(stale_body, planner_headers)
        validate_error(refused, ApiErrorId.STALE_SHIPMENT_VERSION)
        _p7_assert_no_concurrency_handles(refused, "the stale line create")
        _, meta = validate_paginated(
            api.list_shipment_lines({"shipment_id": trailer_id}, planner_headers)
        )
        assert meta["total_count"] == 1, "the 412 created no line"
        assert (
            api.read_entity("get_finished_unit", second_hull["id"], planner_headers)[
                "logistics_status"
            ]
            == "STORED"
        )

        version_b = shipment_version(trailer_id)
        assert version_b == version_a + 1
        retried = api.create_shipment_line(
            dict(stale_body, expected_shipment_version=version_b), planner_headers
        )
        second_line = get_success_data(retried)
        _p7_assert_no_concurrency_handles(retried, "the accepted line create")
        assert second_line["nest_position"] == 2
        assert_decimal_equals(
            second_line["line_nested_cube_m3"], "1.0000", Q_CUBE, "line_nested_cube_m3"
        )

        final = api.read_entity("get_shipment", trailer_id, planner_headers)
        assert_decimal_equals(final["nested_cube_m3"], "3.0000", Q_CUBE, "nested_cube_m3")
        assert_decimal_equals(
            final["loaded_weight_kg"], "48.000", Q_MASS, "loaded_weight_kg"
        )
        assert final["status"] == "LOADING"
        assert final["version"] == version_b + 1


class TestApprovalConcurrency:
    """PRD §2.6: "Approving a warranty claim requires
    `expected_product_model_version` ... A mismatch yields
    `ERR_STALE_PRODUCT_MODEL_VERSION`."
    """

    def test_an_unrelated_patch_invalidates_the_agents_expected_model_version(
        self, api, admin_headers, warranty_agent_headers
    ):
        """A cooling-time amendment has nothing to do with money, yet it moves the
        funding parent's version and defers the payout by one retry.

        PRD.md §2.6: "Approving a warranty claim requires
        `expected_product_model_version`, compared against the `version` of the
        `ProductModel` that owns the warranty reserve being drawn. A mismatch
        yields `ERR_STALE_PRODUCT_MODEL_VERSION`", and on a mismatch "nothing is
        persisted — no child row is created, no ledger is moved, no cascade runs."
        PRD.md §3.9: "The body carries `expected_product_model_version`; a mismatch
        is `ERR_STALE_PRODUCT_MODEL_VERSION` (HTTP 412) and nothing is written,
        because the reserve balance the agent priced against has already moved."
        PRD.md §3.9: under `PRO_RATA_AGE` "a claim at 0 months covers 100.00
        percent"; `pre_fee_gross_cents` is "`msrp_cents` multiplied by the coverage
        percentage divided by 100, multiplied by the claim-type factor — 1.00 for
        `HULL_DEFORMATION`"; `admin_fee_cents` uses "the **first** tier whose
        maximum gross is at or above `pre_fee_gross_cents`, from an ordered ladder
        of 50000 cents at 12.00 percent and 200000 cents at 8.00 percent";
        `storage_deduction_cents` is "exactly 0 when it is `GUIDANCE_VERIFIED`";
        and `net_payout_cents` is "the gross minus the deduction minus the fee".
        PRD.md §3.9: "the model's `warranty_reserve_cents` decreases by
        `net_payout_cents` and its `warranty_paid_cents` increases by the identical
        integer ... Both the model's and the claim's `version` advance by 1."

        Design: Corner/consistency_model/occ_claim_approve_stale_product_model_version_across_an_intervening_patch
        """
        set_clock(CLOCK_START)
        ctx = setup_claim_storage_verified()
        claim_id = ctx["warranty_claim_id"]
        model_id = ctx["product_model_id"]

        claim = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
        assert claim["storage_review_status"] == "GUIDANCE_VERIFIED"
        assert claim["claim_status"] == "UNDER_REVIEW"
        assert claim["months_in_service"] == 0

        model_version_a = product_model_version(model_id)
        patched = get_success_data(
            api.update_product_model(
                model_id, {"min_cooling_minutes": 31}, admin_headers
            )
        )
        assert patched["min_cooling_minutes"] == 31
        model_version_b = patched["version"]
        assert model_version_b == model_version_a + 1

        refused = api.approve_warranty_claim(
            claim_id, approve_claim_payload(model_version_a), warranty_agent_headers
        )
        validate_error(refused, ApiErrorId.STALE_PRODUCT_MODEL_VERSION)
        _p7_assert_no_concurrency_handles(refused, "the stale approval")
        held = api.read_entity("get_product_model", model_id, admin_headers)
        assert_money_equals(held["warranty_reserve_cents"], 500000, "reserve after 412")
        assert_money_equals(held["warranty_paid_cents"], 0, "paid after 412")
        assert (
            api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)[
                "claim_status"
            ]
            == "UNDER_REVIEW"
        )

        retried = api.approve_warranty_claim(
            claim_id, approve_claim_payload(model_version_b), warranty_agent_headers
        )
        approved = get_success_data(retried)
        _p7_assert_no_concurrency_handles(retried, "the accepted approval")
        assert approved["claim_status"] == "APPROVED"
        assert approved["payout_basis"] == "PRO_RATA_AGE"
        assert_money_equals(approved["pre_fee_gross_cents"], 180000, "pre_fee_gross_cents")
        assert_money_equals(approved["storage_deduction_cents"], 0, "storage_deduction_cents")
        assert_money_equals(approved["admin_fee_cents"], 14400, "admin_fee_cents")
        assert_money_equals(approved["net_payout_cents"], 165600, "net_payout_cents")

        model_after = api.read_entity("get_product_model", model_id, admin_headers)
        assert_money_equals(
            model_after["warranty_reserve_cents"], 334400, "warranty_reserve_cents"
        )
        assert_money_equals(
            model_after["warranty_paid_cents"], 165600, "warranty_paid_cents"
        )
        assert_warranty_reserve_conserved(model_after)
        assert model_after["version"] == model_version_b + 1


class TestImmediateVisibility:
    """PRD §2.4 and §3.7: a multi-row cascade is readable in the next request."""

    def test_the_storage_release_cascade_is_fully_readable_in_the_following_request(
        self, api, planner_headers
    ):
        """Releasing the anchor promotes its sibling, re-prices it and re-derives
        the site posture, and every one of those facts is already visible.

        PRD.md §3.7: releasing storage "is the head of **CASCADE-C**: (1) the hull
        moves `STORED` to `UNALLOCATED`, its `warehouse_id`, `storage_zone_code`,
        `stored_at` and `demand_bucket_id` are cleared, its
        `stored_footprint_cube_m3` is set to 0.0000 and `is_zone_anchor` to false;
        (2) when the released hull *was* its nest group's anchor and followers
        remain, the earliest surviving occupant ... is promoted: its
        `is_zone_anchor` becomes true and its `stored_footprint_cube_m3` is
        re-charged to the full `gross_cube_m3` rounded to four decimals. (3) The
        site's `committed_cube_m3`, `utilization_pct` and `posture` are recomputed."
        PRD.md §3.7: "`posture` is `FROZEN` when `utilization_pct` is at or above
        `frozen_threshold_pct`, `RESTRICTED` when it is at or above
        `restricted_threshold_pct` ... and `NORMAL` otherwise."
        PRD.md §3.6: "Hulls are listed with optional ... `is_zone_anchor` filters."
        PRD.md §2.4: `version` "increments by exactly 1 on every persisted
        mutation, including mutations that occur as cascade side effects of a
        request aimed at a different resource."

        Design: Corner/consistency_model/occ_immediate_visibility_of_cascade_derived_fields_in_the_next_request
        """
        set_clock(CLOCK_START)
        ctx = setup_stored_units()
        warehouse_id = ctx["warehouse_id"]
        anchor, follower = ctx["stored_units"][0], ctx["stored_units"][1]

        before = api.read_footprint_summary(warehouse_id, planner_headers)
        zone_before = next(
            z for z in before["zones"] if z["zone_code"] == DEFAULT_ZONE_CODE
        )
        assert_decimal_equals(
            zone_before["committed_cube_m3"], "3.0000", Q_CUBE, "zone committed_cube_m3"
        )
        assert_decimal_equals(
            before["utilization_pct"], "15.00", Q_PERCENT, "utilization_pct"
        )
        assert before["posture"] == "NORMAL"
        assert zone_before["anchor_product_model_ids"] == [ctx["product_model_id"]]

        released_response = api.release_storage(
            anchor["id"], release_storage_payload("Zone rebalance"), planner_headers
        )
        released = get_success_data(released_response)
        _p7_assert_no_concurrency_handles(released_response, "the storage release")
        assert released["logistics_status"] == "UNALLOCATED"
        assert released["warehouse_id"] is None
        assert released["is_zone_anchor"] is False
        assert_decimal_equals(
            released["stored_footprint_cube_m3"], "0.0000", Q_CUBE, "released footprint"
        )

        promoted = api.read_entity("get_finished_unit", follower["id"], planner_headers)
        assert promoted["is_zone_anchor"] is True, "the promotion is not deferred"
        assert_decimal_equals(
            promoted["stored_footprint_cube_m3"], "2.0000", Q_CUBE, "promoted footprint"
        )

        after = api.read_footprint_summary(warehouse_id, planner_headers)
        assert_footprint_summary_consistent(after)
        zone_after = next(
            z for z in after["zones"] if z["zone_code"] == DEFAULT_ZONE_CODE
        )
        assert_decimal_equals(
            zone_after["committed_cube_m3"], "2.0000", Q_CUBE, "zone committed_cube_m3"
        )
        assert_decimal_equals(
            zone_after["remaining_cube_m3"], "18.0000", Q_CUBE, "zone remaining_cube_m3"
        )
        assert_decimal_equals(
            after["utilization_pct"], "10.00", Q_PERCENT, "utilization_pct"
        )
        assert after["posture"] == "NORMAL"

        anchors, meta = validate_paginated(
            api.list_finished_units({"is_zone_anchor": "true"}, planner_headers)
        )
        assert meta["total_count"] == 1
        assert anchors[0]["id"] == follower["id"]
