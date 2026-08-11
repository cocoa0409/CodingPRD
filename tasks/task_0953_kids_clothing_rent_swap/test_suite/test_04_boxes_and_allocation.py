"""Filling a box: frozen capacity, the two box-item axes, packing and shipping."""

from test_helpers import (
    BILLING,
    LOGISTICS,
    WAREHOUSE,
    ApiErrorId,
    assert_box,
    assert_box_item,
    assert_box_slot_conservation,
    assert_unit_conservation,
    allocate_unit,
    create_box,
    create_open_cycle,
    create_style,
    create_unit,
    get_box,
    get_box_item,
    get_cycle,
    get_member,
    get_shipment,
    get_style,
    get_success_data,
    get_unit,
    list_box_items,
    list_units,
    mint_label,
    pack_box,
    raise_charge,
    setup_paused_member,
    setup_plan_and_member,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBoxCreation:
    def test_slot_capacity_is_frozen_from_the_members_plan(self, api):
        """PRD §3.3: "the new box is `DRAFT`, its `member_id` is denormalised
        from the cycle's owner, its `slot_capacity` is copied from the member's
        plan `slots_per_box` and then **frozen for the life of the box** — a
        later plan edit does not resize an open box — and its
        `outbound_shipment_id` is null until it ships."

        Design: Corner/entities/corner_box_slot_capacity_frozen_from_plan_at_creation
        """
        _, member = setup_plan_and_member(
            plan={"tier": "PLUS", "slots_per_box": 3, "swaps_per_cycle": 2,
                  "monthly_fee_cents": 7000}
        )
        cycle = create_open_cycle(member["id"])
        box = validate_success(api.create_box({"cycle_id": cycle["id"]}, WAREHOUSE), 201)

        assert_box(box)
        assert box["slot_capacity"] == 3
        assert box["slots_free"] == 3
        assert box["status"] == "DRAFT"
        assert box["member_id"] == member["id"]
        assert box["outbound_shipment_id"] is None


class TestAllocation:
    def test_a_fresh_box_item_starts_on_both_initial_axis_values(self, api):
        """PRD §3.3: "Allocation moves the chosen unit `IN_STOCK → RESERVED`,
        creates a `BoxItem` with `fulfillment_status` `ALLOCATED` and
        `settlement_status` `OPEN`, assigns `slot_index` as a zero-based
        position in ascending order of allocation `created_at`, sets
        `is_capsule_item` true exactly when the allocated unit's `capsule_id` is
        non-null, copies `embargo_until` from that capsule when it is, and
        decrements the box's `slots_free` by 1."
        PRD §3.3: "The item's `return_shipment_id` starts null, its `days_late`,
        `late_fee_cents` and `damage_fee_cents` start at 0, and its
        `assessed_grade` starts null."

        Design: Corner/entities/corner_box_item_starts_on_both_initial_axis_values
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2})
        style = create_style(sku="SKU-BI-5", name="Item Style", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])

        item = validate_success(
            api.allocate_into_box(box["id"], {"unit_id": unit["id"]}, WAREHOUSE), 201
        )
        assert_box_item(item)
        assert item["fulfillment_status"] == "ALLOCATED"
        assert item["settlement_status"] == "OPEN"
        assert item["slot_index"] == 0
        assert item["is_capsule_item"] is False
        assert item["embargo_until"] is None
        assert item["days_late"] == 0
        assert item["late_fee_cents"] == 0
        assert get_unit(unit["id"])["state"] == "RESERVED"
        assert get_box(box["id"])["slots_free"] == 1

    def test_allocating_past_the_frozen_capacity_is_refused(self, api):
        """PRD §2.6 rung 44: "Allocating a unit must not push the box's occupied
        slots above its `slot_capacity`. Otherwise `ERR_BOX_SLOTS_EXHAUSTED`
        (409). Applies to `POST /kidswear/boxes/{box_id}/allocate`."
        PRD §3.3: "Allocating past the frozen capacity is refused with
        `ERR_BOX_SLOTS_EXHAUSTED`"

        Design: Corner/validations/corner_val_allocating_past_the_slot_capacity_is_rejected
        """
        _, member = setup_plan_and_member(
            plan={"tier": "STARTER", "slots_per_box": 1, "monthly_fee_cents": 4000}
        )
        style = create_style(sku="SKU-V6-5", name="Slot Tee", size_code="5")
        first = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        second = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        allocate_unit(box["id"], unit_id=first["id"])

        resp = api.allocate_into_box(box["id"], {"unit_id": second["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_BOX_SLOTS_EXHAUSTED.value, 409)
        assert get_unit(second["id"])["state"] == "IN_STOCK"
        assert get_box(box["id"])["slots_free"] == 0


class TestPackingAndShipping:
    def test_packing_a_partially_filled_box_is_refused(self, api):
        """PRD §3.3: "It requires that the count of the box's `ALLOCATED` items
        equals the box's `slot_capacity` — a partially filled box is refused
        with `ERR_BOX_NOT_FULL` — and that the owning cycle is `OPEN`."

        Design: Corner/state_machines/corner_sm_box_pack_with_unfilled_slots_is_rejected
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2})
        style = create_style(sku="SKU-SM4-5", name="SM Four Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        allocate_unit(box["id"], unit_id=unit["id"])

        resp = api.pack_box(box["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_BOX_NOT_FULL.value, 409)

        after = get_box(box["id"])
        assert after["status"] == "DRAFT"
        assert after["slots_free"] == 1

    def test_shipping_a_draft_box_is_an_invalid_box_state(self, api):
        """PRD §2.6 rung 24: "`Box.status` is a declared from-state for the
        requested box transition. Otherwise `ERR_BOX_INVALID_STATE` (409).
        Applies to box transition endpoints."
        PRD §3.3: "Shipping is a `LogisticsCoordinator` action that moves the
        box `PACKED → SHIPPED` under a supplied `label_id`."

        Design: Corner/errors/corner_err_shipping_an_unpacked_box_is_rejected
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2})
        style = create_style(sku="SKU-Y2-5", name="State Two Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        allocate_unit(box["id"], unit_id=unit["id"])
        label = mint_label(member["id"], "OUTBOUND")

        resp = api.ship_box(box["id"], {"label_id": label["id"]}, LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_BOX_INVALID_STATE.value, 409)

        assert get_box(box["id"])["status"] == "DRAFT"
        assert get_unit(unit["id"])["state"] == "RESERVED"
        assert validate_success(
            api.get_shipping_label(label["id"], LOGISTICS)
        )["status"] == "ISSUED"

    def test_shipping_a_box_under_a_return_label_is_a_direction_mismatch(self, api):
        """PRD §3.3: "The label must have `direction` `OUTBOUND` and `status`
        `ISSUED`, and the logical clock must not have passed the label's
        `expires_at`; a label of the wrong direction is refused with
        `ERR_LABEL_DIRECTION_MISMATCH`, a label in the wrong status with
        `ERR_LABEL_INVALID_STATE`, and an expired label with
        `ERR_LABEL_EXPIRED`."

        Design: Corner/errors/corner_err_box_shipped_under_a_return_label_is_rejected
        """
        _, member = setup_plan_and_member()
        style = create_style(sku="SKU-XLD-5", name="Dir Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        allocate_unit(box["id"], unit_id=unit["id"])
        pack_box(box["id"])
        label = mint_label(member["id"], "RETURN")

        resp = api.ship_box(box["id"], {"label_id": label["id"]}, LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_LABEL_DIRECTION_MISMATCH.value, 409)

        after = get_box(box["id"])
        assert after["status"] == "PACKED"
        assert after["outbound_shipment_id"] is None
        assert validate_success(
            api.get_shipping_label(label["id"], LOGISTICS)
        )["status"] == "ISSUED"

    def test_the_shipping_cascade_is_visible_immediately(self, api):
        """PRD §3.3: "Shipping creates a `Shipment` with `direction` `OUTBOUND`
        and `status` `CREATED`, sets the box's `outbound_shipment_id`, advances
        every `ALLOCATED` item to `SHIPPED`, advances every `RESERVED` unit to
        `OUT`, and bumps versions."
        PRD §3.3: "The `slots_free` figure is always `slot_capacity` minus the
        count of the box's items whose `fulfillment_status` is `ALLOCATED`,
        `SHIPPED`, `WITH_MEMBER` or `RETURNING`, minus the count of items whose
        `settlement_status` is `BOUGHT_OUT`."

        The success status is deliberately not pinned: PRD §4 says "Creation
        endpoints answer HTTP 201 with the newly created resource in `data`;
        every other successful operation answers HTTP 200 with the affected
        resource in `data`", and it describes this endpoint as "Ship a packed
        box under an OUTBOUND label; creates the outbound shipment" — so a
        faithful implementer may answer 200 with the box or 201 with the new
        shipment.  Only the cascade below is PRD-determined.

        Design: Corner/consistency_model/corner_consistency_cascade_is_visible_in_the_same_response
        """
        _, member = setup_plan_and_member()
        style = create_style(sku="SKU-Z1-5", name="Consistency Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        pack_box(box["id"])
        label = mint_label(member["id"], "OUTBOUND")

        get_success_data(api.ship_box(box["id"], {"label_id": label["id"]}, LOGISTICS))

        after_box = get_box(box["id"])
        assert after_box["status"] == "SHIPPED"
        assert after_box["outbound_shipment_id"] is not None
        assert get_shipment(after_box["outbound_shipment_id"])["status"] == "CREATED"
        assert get_box_item(item["id"])["fulfillment_status"] == "SHIPPED"
        assert get_unit(unit["id"])["state"] == "OUT"
        assert after_box["slots_free"] == 0


class TestCompensatingActionsConservePhysicalUnits:
    def test_the_delinquency_cascade_returns_the_reserved_unit_to_stock(self, api):
        """PRD §3.1: "Falling into `DELINQUENT` cascades: every `OPEN` or
        `SWAP_CLOSED` cycle of the member moves to `HELD`; every box item of the
        member still in `ALLOCATED` moves to `CANCELLED`; each such item's
        reserved unit returns from `RESERVED` to `IN_STOCK`; a `DRAFT` box moves
        to `CANCELLED` as its allocated items are cancelled; and the member's
        `version` increments by 1."
        PRD §2.10: "For each `GarmentStyle`, its `units_ever_acquired` equals the
        total number of that style's units counted across all eight circulation
        states: `IN_STOCK`, `RESERVED`, `OUT`, `INBOUND`, `PROCESSING`,
        `LOST_IN_TRANSIT`, `RETIRED` and `SOLD`."

        Design: Difficulty/compensating_invariant/allocation_then_delinquency_cancellation_conserves_physical_units
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        style = create_style(sku="SKU-C1-5", name="Cons Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        assert get_unit(unit["id"])["state"] == "RESERVED"

        raise_charge(member["id"], "DAMAGE_FEE", 20000)

        assert get_member(member["id"])["status"] == "DELINQUENT"
        assert get_unit(unit["id"])["state"] == "IN_STOCK"
        assert get_box_item(item["id"])["fulfillment_status"] == "CANCELLED"
        refreshed_style = get_style(style["id"])
        assert refreshed_style["units_ever_acquired"] == 1
        assert_unit_conservation(refreshed_style, list_units(style_id=style["id"]))

    def test_waiving_the_charge_restores_standing_and_conserves_the_box_slots(self, api):
        """PRD §3.11: "A `BillingAgent` may also waive an open charge by
        supplying a `waive_reason`, which moves it to `WAIVED` with
        `net_due_cents` set to 0, recomputes the outstanding balance, and may
        return the member `DELINQUENT → ACTIVE`."
        PRD §3.1: "Recovering to `ACTIVE` reverses the hold: every `HELD` cycle
        returns to the status implied by the current clock — `OPEN` while the
        clock is on or before `swap_by_at`, `SWAP_CLOSED` while it is on or
        before `return_due_at`, `RETURN_DUE` while it is on or before
        `grace_ends_at`, and `GRACE` thereafter — and the member's `version`
        increments again."
        PRD §2.10: "For each `Box`, its `slot_capacity` equals its `slots_free`
        plus the number of its items whose `fulfillment_status` is one of
        `ALLOCATED`, `SHIPPED`, `WITH_MEMBER` or `RETURNING`, plus the number of
        its items whose `settlement_status` is `BOUGHT_OUT`."

        Design: Difficulty/compensating_invariant/allocation_then_delinquency_cancellation_conserves_physical_units
        """
        _, member = setup_plan_and_member(member={"auto_apply_credit": False})
        style = create_style(sku="SKU-C1B-5", name="Cons Tee Two", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        allocate_unit(box["id"], unit_id=unit["id"])

        charge = validate_success(
            api.create_charge_adjustment(member["id"],
                                         {"charge_type": "DAMAGE_FEE", "amount_cents": 20000},
                                         BILLING),
            201,
        )
        validate_success(
            api.waive_charge_entry(charge["id"], {"waive_reason": "operator error"}, BILLING)
        )

        after_member = get_member(member["id"])
        assert after_member["status"] == "ACTIVE"
        assert after_member["outstanding_balance_cents"] == 5000
        assert get_cycle(cycle["id"])["status"] == "OPEN"

        after_box = get_box(box["id"])
        assert after_box["slot_capacity"] == 1
        assert after_box["slots_free"] == 1
        assert_box_slot_conservation(after_box, list_box_items(box_id=box["id"]))
