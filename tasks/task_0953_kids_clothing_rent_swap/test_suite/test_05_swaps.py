"""Partial swaps: shape, entitlement, ownership, the cycle OCC guard and conservation."""

from test_helpers import (
    ADMIN,
    WAREHOUSE,
    ApiErrorId,
    assert_same_instant,
    allocate_unit,
    approve_swap,
    create_active_member,
    create_box,
    create_open_cycle,
    create_plan,
    create_style,
    create_swap_request,
    create_unit,
    fulfill_swap,
    get_box,
    get_box_item,
    get_cycle,
    get_member,
    get_swap_request,
    get_unit,
    list_box_items,
    make_member_headers,
    raise_charge,
    set_clock,
    setup_delivered_box,
    setup_plan_and_member,
    setup_returned_items,
    submit_swap,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSwapShapeAndEntitlement:
    def test_mismatched_array_lengths_are_a_swap_shape_failure(self, api):
        """PRD §2.6 rung 46: "The number of entries in `requested_style_ids`
        equals the number of entries in `return_box_item_ids`, and both counts
        are at least 1 and at most the plan's `slots_per_box`. Otherwise
        `ERR_SWAP_SHAPE_INVALID` (422)."
        PRD §3.4: "The two arrays must be the same length, each must hold at
        least one entry, and neither may hold more entries than the plan's
        `slots_per_box`; a violation of any of those three conditions is refused
        with `ERR_SWAP_SHAPE_INVALID`."

        Design: Corner/validations/corner_val_swap_with_mismatched_array_lengths_is_rejected
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 1, "swaps_per_cycle": 2})
        style = create_style(sku="SKU-V7-5", name="Shape Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        version = get_cycle(cycle["id"])["version"]

        resp = api.create_swap_request(
            cycle["id"],
            {"return_box_item_ids": [item["id"]],
             "requested_style_ids": [style["id"], style["id"]],
             "expected_cycle_version": version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SWAP_SHAPE_INVALID.value, 422)

        _, meta = validate_paginated(api.list_swap_requests(WAREHOUSE,
                                                            {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0
        assert get_cycle(cycle["id"])["swaps_used"] == 0

    def test_submitting_with_no_remaining_entitlement_is_refused(self, api):
        """PRD §2.6 rung 45: "At least one swap entitlement must remain for the
        cycle. Otherwise `ERR_SWAP_ENTITLEMENT_EXHAUSTED` (409). Applies to
        `POST /kidswear/swap-requests/{swap_request_id}/submit`."
        PRD §3.4: "If no entitlement remains, submission is refused with
        `ERR_SWAP_ENTITLEMENT_EXHAUSTED`."

        Design: Corner/validations/corner_val_swap_submit_with_zero_entitlement_is_rejected
        """
        _, member = setup_plan_and_member(
            plan={"tier": "STARTER", "slots_per_box": 1, "swaps_per_cycle": 0,
                  "monthly_fee_cents": 4000}
        )
        style = create_style(sku="SKU-V8-5", name="Entitlement Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        swap = create_swap_request(member["id"], cycle["id"], [item["id"]], [style["id"]])

        resp = api.submit_swap_request(swap["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_SWAP_ENTITLEMENT_EXHAUSTED.value, 409)
        assert get_swap_request(swap["id"])["status"] == "DRAFT"
        assert get_cycle(cycle["id"])["status"] == "OPEN"

    def test_a_swap_naming_another_households_item_is_refused(self, api):
        """PRD §2.6 rung 13: "Every identifier inside an array body field —
        `return_box_item_ids` and `requested_style_ids` — resolves and belongs
        to the addressed member's own resources. Otherwise
        `ERR_REFERENCE_NOT_OWNED` (422). Applies to
        `POST /kidswear/cycles/{cycle_id}/swap-requests`."
        PRD §3.4: "Every identifier inside either array must resolve *and*
        belong to the addressed member's own resources; a stranger's box item or
        an unresolvable style is refused with `ERR_REFERENCE_NOT_OWNED`."

        Design: Corner/validations/corner_val_swap_referencing_another_members_item_is_rejected
        """
        plan = create_plan(slots_per_box=1, swaps_per_cycle=2)
        style = create_style(sku="SKU-V18-5", name="Shared Tee", size_code="5")
        unit_a = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        unit_b = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        member_a = create_active_member(plan["id"], email="v18a@kidswear.test")
        member_b = create_active_member(plan["id"], email="v18b@kidswear.test")

        cycle_a = create_open_cycle(member_a["id"])
        box_a = create_box(cycle_a["id"])
        allocate_unit(box_a["id"], unit_id=unit_a["id"])
        cycle_b = create_open_cycle(member_b["id"])
        box_b = create_box(cycle_b["id"])
        item_b = allocate_unit(box_b["id"], unit_id=unit_b["id"])

        version = get_cycle(cycle_a["id"])["version"]
        resp = api.create_swap_request(
            cycle_a["id"],
            {"return_box_item_ids": [item_b["id"]],
             "requested_style_ids": [style["id"]],
             "expected_cycle_version": version},
            make_member_headers(member_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_OWNED.value, 422)

        _, meta = validate_paginated(api.list_swap_requests(WAREHOUSE,
                                                            {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0
        assert get_box_item(item_b["id"])["fulfillment_status"] == "ALLOCATED"

    def test_fulfilment_before_the_returned_item_arrives_is_refused(self, api):
        """PRD §3.4: "A `WarehouseOperator` moves the request `APPROVED →
        FULFILLED` only once **every** identifier in `return_box_item_ids` names
        an item whose `fulfillment_status` has reached `RECEIVED`; a premature
        attempt is refused with `ERR_RETURN_ITEM_NOT_RECEIVED`."
        PRD §3.4: "On success `allocated_unit_ids` is populated, each selected
        unit moves `IN_STOCK → RESERVED`, `slot_delta` is computed and pinned to
        0, and the request's `version` increments by 1."

        Design: Corner/validations/corner_val_swap_fulfilment_before_the_return_is_received_is_rejected
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2, "swaps_per_cycle": 1})
        style_a = create_style(sku="SKU-V19-A", name="Nineteen A", size_code="5")
        style_b = create_style(sku="SKU-V19-B", name="Nineteen B", size_code="5",
                               retail_price_cents=3200, category="BOTTOM")
        unit_a1 = create_unit(style_a["id"], acquired_at="2026-02-01T00:00:00Z")
        unit_a2 = create_unit(style_a["id"], acquired_at="2026-02-01T00:00:00Z")
        unit_b1 = create_unit(style_b["id"], acquired_at="2026-02-01T00:00:00Z")

        scenario = setup_delivered_box(member, [unit_a1, unit_a2])
        first_item = scenario["items"][0]
        swap = create_swap_request(member["id"], scenario["cycle"]["id"],
                                   [first_item["id"]], [style_b["id"]])
        submit_swap(member["id"], swap["id"])
        approve_swap(swap["id"])

        resp = api.fulfill_swap_request(swap["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_RETURN_ITEM_NOT_RECEIVED.value, 409)

        assert get_swap_request(swap["id"])["status"] == "APPROVED"
        assert get_cycle(scenario["cycle"]["id"])["swaps_used"] == 0
        assert get_unit(unit_b1["id"])["state"] == "RESERVED"
        assert get_box_item(first_item["id"])["fulfillment_status"] == "WITH_MEMBER"


class TestSwapConcurrency:
    def test_a_stale_cycle_version_is_refused_at_the_concurrency_gate(self, api):
        """PRD §2.8: "A `POST /kidswear/cycles/{cycle_id}/swap-requests` request
        must carry `expected_cycle_version` holding the client's last observed
        `version` of the target `Cycle`. If the cycle's `version` has advanced
        since the client read it, the create is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
        PRD §2.8: "A successful create increments the cycle's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/corner_ccl_occ_stale_cycle_version_on_swap_creation
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2, "swaps_per_cycle": 2})
        style = create_style(sku="SKU-O1-5", name="OCC Tee", size_code="5")
        unit_one = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        unit_two = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item_one = allocate_unit(box["id"], unit_id=unit_one["id"])
        item_two = allocate_unit(box["id"], unit_id=unit_two["id"])

        stale_version = get_cycle(cycle["id"])["version"]
        first = create_swap_request(member["id"], cycle["id"], [item_one["id"]],
                                    [style["id"]], stale_version)

        resp = api.create_swap_request(
            cycle["id"],
            {"return_box_item_ids": [item_two["id"]],
             "requested_style_ids": [style["id"]],
             "expected_cycle_version": stale_version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION.value, 412)

        _, meta = validate_paginated(api.list_swap_requests(
            WAREHOUSE, {"cycle_id": cycle["id"], "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert get_swap_request(first["id"])["status"] == "DRAFT"


class TestGateOrderingOnSubmission:
    def test_the_state_gate_pre_empts_the_entitlement_gate(self, api):
        """PRD §2.5: "The gates form a total order, and they are evaluated
        strictly in ascending order. The **first** gate that fails decides the
        error the caller receives; no later gate is consulted once an earlier
        one has refused."
        PRD §2.6 rung 23: "`Cycle.status` is `OPEN` for swap creation, swap
        submission and box allocation. Otherwise `ERR_CYCLE_NOT_OPEN` (409).
        Applies to `POST /kidswear/cycles/{cycle_id}/swap-requests`,
        `POST /kidswear/swap-requests/{swap_request_id}/submit` and
        `POST /kidswear/boxes/{box_id}/allocate`."
        PRD §2.6 rung 45: "At least one swap entitlement must remain for the
        cycle. Otherwise `ERR_SWAP_ENTITLEMENT_EXHAUSTED` (409). Applies to
        `POST /kidswear/swap-requests/{swap_request_id}/submit`."

        Design: Difficulty/priority_pair_validation_conflict/cycle_not_open_wins_over_swap_entitlement_exhausted
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 1, "swaps_per_cycle": 0})
        style = create_style(sku="SKU-P1-5", name="Prio Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        swap = create_swap_request(member["id"], cycle["id"], [item["id"]], [style["id"]])

        set_clock("2026-05-22T00:00:00Z")
        validate_success(api.close_swap_window(cycle["id"], ADMIN))

        resp = api.submit_swap_request(swap["id"], make_member_headers(member["id"]))
        error = validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_SWAP_ENTITLEMENT_EXHAUSTED.value

    def test_the_masked_submission_consumes_neither_state_nor_entitlement(self, api):
        """PRD §2.5: "The **first** gate that fails decides the error the caller
        receives; no later gate is consulted once an earlier one has refused."
        PRD §3.2: "Closing the window rejects every one of the cycle's swap
        requests still in `DRAFT` or `SUBMITTED`, writing `MEMBER_STANDING` as
        their `rejection_reason`, and bumps the cycle's `version`."
        PRD §3.2: "Alongside these the cycle also carries `swaps_used`, the
        count of its swap requests that reached `FULFILLED`"

        Design: Difficulty/priority_pair_validation_conflict/cycle_not_open_wins_over_swap_entitlement_exhausted
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 1, "swaps_per_cycle": 0})
        style = create_style(sku="SKU-P1B-5", name="Prio Tee Two", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        swap = create_swap_request(member["id"], cycle["id"], [item["id"]], [style["id"]])

        set_clock("2026-05-22T00:00:00Z")
        validate_success(api.close_swap_window(cycle["id"], ADMIN))
        validate_error(
            api.submit_swap_request(swap["id"], make_member_headers(member["id"])),
            ApiErrorId.ERR_CYCLE_NOT_OPEN.value, 409,
        )

        assert get_cycle(cycle["id"])["swaps_used"] == 0
        assert get_cycle(cycle["id"])["status"] == "SWAP_CLOSED"


class TestSwapWindowBoundary:
    def test_submitting_at_exactly_swap_by_at_succeeds(self, api):
        """PRD §2.6 rung 33: "A swap may be created or submitted only while the
        logical clock is on or before the cycle's `swap_by_at`; the boundary is
        **inclusive**, so a swap submitted at exactly `swap_by_at` is accepted."
        PRD §3.4: "Submission requires the request to be `DRAFT`, the cycle to
        be `OPEN`, and the logical clock to be on or before `swap_by_at` — at
        exactly `swap_by_at` submission still succeeds."

        Design: Difficulty/boundary_precision_check/swap_submitted_exactly_at_swap_by_at_is_accepted
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 1, "swaps_per_cycle": 1})
        style = create_style(sku="SKU-B1-5", name="Bound Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        swap = create_swap_request(member["id"], cycle["id"], [item["id"]], [style["id"]])

        set_clock("2026-05-21T00:00:00Z")
        submitted = validate_success(
            api.submit_swap_request(swap["id"], make_member_headers(member["id"]))
        )
        assert submitted["status"] == "SUBMITTED"

    def test_the_inclusive_boundary_sits_twenty_days_after_the_start(self, api):
        """PRD §3.2: "`swap_by_at` is `start_at` plus `SWAP_BY_OFFSET_DAYS`,
        twenty days."
        PRD §3.2: "a swap is allowed while the clock is *on or before*
        `swap_by_at`, so a swap submitted at exactly `swap_by_at` succeeds"

        Design: Difficulty/boundary_precision_check/swap_submitted_exactly_at_swap_by_at_is_accepted
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 1, "swaps_per_cycle": 1})
        style = create_style(sku="SKU-B1B-5", name="Bound Tee Two", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        swap = create_swap_request(member["id"], cycle["id"], [item["id"]], [style["id"]])

        assert_same_instant(cycle["swap_by_at"], "2026-05-21T00:00:00.000Z",
                            "Cycle.swap_by_at")
        set_clock("2026-05-21T00:00:00Z")
        validate_success(api.submit_swap_request(swap["id"],
                                                 make_member_headers(member["id"])))
        assert get_swap_request(swap["id"])["status"] == "SUBMITTED"
        assert get_cycle(cycle["id"])["status"] == "OPEN"


class TestPartialSwapConservation:
    def _fulfilled_partial_swap(self):
        _, member = setup_plan_and_member(plan={"slots_per_box": 2, "swaps_per_cycle": 1})
        style_a = create_style(sku="SKU-C3-A", name="Swap Style A", size_code="5")
        style_b = create_style(sku="SKU-C3-B", name="Swap Style B", size_code="5",
                               retail_price_cents=3500, category="BOTTOM")
        unit_a1 = create_unit(style_a["id"], acquired_at="2026-01-01T00:00:00Z")
        unit_a2 = create_unit(style_a["id"], acquired_at="2026-01-01T00:00:00Z")
        unit_b1 = create_unit(style_b["id"], acquired_at="2026-01-01T00:00:00Z")

        scenario = setup_delivered_box(member, [unit_a1, unit_a2])
        item_one, item_two = scenario["items"]
        swap = create_swap_request(member["id"], scenario["cycle"]["id"],
                                   [item_one["id"]], [style_b["id"]])
        submit_swap(member["id"], swap["id"])
        approve_swap(swap["id"])
        setup_returned_items(member, [item_one["id"]])
        fulfill_swap(swap["id"])
        return {
            "member": member, "cycle": scenario["cycle"], "box": scenario["box"],
            "swap": swap, "item_one": item_one, "item_two": item_two,
            "unit_b1": unit_b1,
        }

    def test_a_partial_swap_fulfils_with_a_zero_slot_delta(self, api):
        """PRD §3.4: "The **conserving** property of a partial swap is enforced
        here: `slot_delta` is the number of allocated units minus the number of
        returned items, and it must be exactly zero, so returning two of five
        items and requesting two replacements leaves the box's `slots_free`
        unchanged."
        PRD §3.4: "Fulfilment creates one new box item per entry in
        `allocated_unit_ids`, each with `fulfillment_status` `ALLOCATED`,
        increments the cycle's `swaps_used` by 1, and bumps the request's
        `version`."

        Design: Difficulty/compensating_invariant/partial_swap_fulfilment_conserves_slot_and_swap_entitlements
        """
        world = self._fulfilled_partial_swap()
        swap = get_swap_request(world["swap"]["id"])
        assert swap["status"] == "FULFILLED"
        assert swap["slot_delta"] == 0
        assert get_cycle(world["cycle"]["id"])["swaps_used"] == 1

    def test_the_swap_leaves_the_boxs_free_slots_unchanged(self, api):
        """PRD §2.10: "For each `Box`, its `slot_capacity` equals its
        `slots_free` plus the number of its items whose `fulfillment_status` is
        one of `ALLOCATED`, `SHIPPED`, `WITH_MEMBER` or `RETURNING`, plus the
        number of its items whose `settlement_status` is `BOUGHT_OUT`."
        PRD §3.4: "Fulfilment creates one new box item per entry in
        `allocated_unit_ids`, each with `fulfillment_status` `ALLOCATED`,
        increments the cycle's `swaps_used` by 1, and bumps the request's
        `version`."

        Design: Difficulty/compensating_invariant/partial_swap_fulfilment_conserves_slot_and_swap_entitlements
        """
        world = self._fulfilled_partial_swap()
        box = get_box(world["box"]["id"])
        assert box["slot_capacity"] == 2
        assert box["slots_free"] == 0
        assert get_box_item(world["item_one"]["id"])["fulfillment_status"] == "RECEIVED"
        assert get_box_item(world["item_two"]["id"])["fulfillment_status"] == "WITH_MEMBER"

        replacements = [i for i in list_box_items(box_id=box["id"])
                        if i["fulfillment_status"] == "ALLOCATED"]
        assert len(replacements) == 1
        assert get_unit(world["unit_b1"]["id"])["state"] == "RESERVED"
