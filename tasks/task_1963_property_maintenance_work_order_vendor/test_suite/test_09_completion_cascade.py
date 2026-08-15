"""Completion cascade: part consumption, parts_total, chargeback creation, and
immediate read-after-write visibility."""
from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    complete_as_technician,
    create_part,
    get_part,
    make_technician_headers,
    reserve_part,
    setup_in_progress_work_order,
    setup_signed_off_work_order,
    sign_off,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_two_reserved_lines(api, property_name="Consume Property", unit="108"):
    """In-progress signed-off order with part A x3 (unit 100) and part B x1 (unit 50) reserved."""
    bundle = setup_in_progress_work_order(property_name, unit_number=unit)
    part_a = create_part(bundle["property"]["id"], sku="A-1", name="Part A",
                         unit_cost_cents=100, reorder_level=2, initial_stock=6)
    part_b = create_part(bundle["property"]["id"], sku="B-1", name="Part B",
                         unit_cost_cents=50, reorder_level=0, initial_stock=4)
    tech = make_technician_headers(bundle["technician"]["id"])
    wop_a = reserve_part(bundle["work_order"]["id"], part_a["id"], 3, tech)
    wop_b = reserve_part(bundle["work_order"]["id"], part_b["id"], 1, tech)
    sign_off(bundle["work_order"]["id"], bundle["resident"]["id"])
    bundle.update({"part_a": part_a, "part_b": part_b, "wop_a": wop_a, "wop_b": wop_b})
    return bundle


class TestCompletionConsumptionCascade:
    def test_completion_consumes_reserved_lines(self, api):
        """PRD §3.4: "Then the stock cascade runs: every work-order-part line of this work order still in `RESERVED` status moves to `CONSUMED`; for each consumed line the part's `reserved_quantity` decreases by the line's quantity (its `quantity_on_hand` is unchanged, having been debited at reservation time); every mutated part's `restock_status` is recomputed per the ledger rule; and the work order's `parts_total_cents` is recomputed as the sum of `line_total_cents` over all its `CONSUMED` lines."

        Design: Difficulty/transitive_cascade/completion_consumption_cascade_depth3
        """
        bundle = _setup_two_reserved_lines(api)
        wo_id = bundle["work_order"]["id"]
        done = complete_as_technician(wo_id, bundle["technician"]["id"],
                                      photo_urls=["https://x/p1.jpg"])
        assert done["status"] == "COMPLETED"

        wop_a = validate_success(
            api.get_work_order_part(bundle["wop_a"]["id"], MANAGER), 200
        )
        wop_b = validate_success(
            api.get_work_order_part(bundle["wop_b"]["id"], MANAGER), 200
        )
        assert wop_a["status"] == "CONSUMED"
        assert wop_b["status"] == "CONSUMED"

    def test_completion_writes_off_stock_and_recomputes_parts_total(self, api):
        """PRD §3.4: "Then the stock cascade runs: every work-order-part line of this work order still in `RESERVED` status moves to `CONSUMED`; for each consumed line the part's `reserved_quantity` decreases by the line's quantity (its `quantity_on_hand` is unchanged, having been debited at reservation time); every mutated part's `restock_status` is recomputed per the ledger rule; and the work order's `parts_total_cents` is recomputed as the sum of `line_total_cents` over all its `CONSUMED` lines."

        Design: Difficulty/transitive_cascade/completion_consumption_cascade_depth3
        """
        bundle = _setup_two_reserved_lines(api)
        wo_id = bundle["work_order"]["id"]
        done = complete_as_technician(wo_id, bundle["technician"]["id"],
                                      photo_urls=["https://x/p1.jpg"])
        part_a = get_part(bundle["part_a"]["id"])
        # Debited to 3 at reserve time; consumption leaves on_hand untouched and
        # drains the reservation.
        assert part_a["quantity_on_hand"] == 3
        assert part_a["reserved_quantity"] == 0
        assert done["parts_total_cents"] == 350, "3*100 + 1*50 over CONSUMED lines"


class TestPartsTotalFiltering:
    def test_parts_total_counts_consumed_lines_only(self, api):
        """PRD §3.4: "and the work order's `parts_total_cents` is recomputed as the sum of `line_total_cents` over all its `CONSUMED` lines."

        Design: Corner/calculations/parts_total_counts_consumed_only
        """
        bundle = setup_in_progress_work_order("Sum Property", unit_number="303")
        part_a = create_part(bundle["property"]["id"], sku="A-2", name="Part A",
                             unit_cost_cents=100, reorder_level=0, initial_stock=10)
        part_b = create_part(bundle["property"]["id"], sku="B-2", name="Part B",
                             unit_cost_cents=50, reorder_level=0, initial_stock=10)
        tech = make_technician_headers(bundle["technician"]["id"])
        wo_id = bundle["work_order"]["id"]
        reserve_part(wo_id, part_a["id"], 2, tech)
        wop_b = reserve_part(wo_id, part_b["id"], 1, tech)
        # The released line must not contribute to the completion sum.
        validate_success(api.release_part(wo_id, wop_b["id"], {}, tech), 200)
        sign_off(wo_id, bundle["resident"]["id"])
        done = complete_as_technician(wo_id, bundle["technician"]["id"],
                                      photo_urls=["https://x/s1.jpg"])
        assert done["parts_total_cents"] == 200, "only the CONSUMED line A (2 * 100)"


class TestChargebackCreationOnDamage:
    def test_complete_with_damage_creates_pending_chargeback(self, api):
        """PRD §3.4: "Finally, if `damage_reported` is true, a Chargeback springs into existence in `PENDING` status, bound to this work order and to the work order's `resident_id`, with `provisional_amount_cents` set to the raw `estimated_damage_cost_cents` from the completion payload — the technician's unrounded field estimate, captured as-is with no rounding applied."

        Design: Corner/endpoints/complete_with_damage_creates_pending_chargeback
        """
        bundle = setup_signed_off_work_order(property_name="CbCreate Property",
                                             unit_number="502")
        wo_id = bundle["work_order"]["id"]
        done = complete_as_technician(
            wo_id, bundle["technician"]["id"],
            photo_urls=["https://x/m1.jpg"],
            damage_reported=True, estimated_damage_cost_cents=7000,
        )
        assert done["status"] == "COMPLETED"

        data, meta = validate_paginated(
            api.list_chargebacks(MANAGER, params={"work_order_id": wo_id})
        )
        assert meta["total_count"] == 1, "exactly one chargeback springs from the damage"
        cb = data[0]
        assert cb["status"] == "PENDING"
        assert cb["provisional_amount_cents"] == 7000
        assert cb["resident_id"] == bundle["resident"]["id"]


class TestImmediateConsistency:
    def test_completion_side_effects_visible_immediately(self, api):
        """PRD §2.9: "All side effects of a single operation commit atomically with the primary transition and are visible in the response and in every subsequent read."
        PRD §3.4: "A successful completion stamps `completed_at` with the current logical clock and computes `completion_sla_breached` as whether that stamp is strictly later than `completion_due_at`."

        Design: Corner/consistency_model/immediate_visibility_of_completion_side_effects
        """
        bundle = setup_signed_off_work_order(property_name="Imm Property",
                                             unit_number="801")
        wo_id = bundle["work_order"]["id"]
        done = complete_as_technician(
            wo_id, bundle["technician"]["id"],
            photo_urls=["https://x/i1.jpg"],
            damage_reported=True, estimated_damage_cost_cents=2500,
        )
        # The mutating response itself carries the new state.
        assert done["status"] == "COMPLETED"
        assert_instant_equals(done["completed_at"], "2026-08-01T00:00:00Z", "completed_at")
        assert done["completion_sla_breached"] is False
        # The very next read already sees the cascade-created chargeback.
        data, meta = validate_paginated(
            api.list_chargebacks(DISPATCHER, params={"work_order_id": wo_id})
        )
        assert meta["total_count"] == 1
        assert data[0]["status"] == "PENDING"
