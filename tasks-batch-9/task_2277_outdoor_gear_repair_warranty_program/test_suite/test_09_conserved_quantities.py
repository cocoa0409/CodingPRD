"""Conserved quantities: what a compensating operation gives back must balance.

Three ledgers in this system are closed: the stockroom's reserved units
(PRD §2.10, §3.8), a technician's open bench minutes (PRD §3.8) and a service
centre's open warranty exposure (PRD §2.9, §3.9). Each test below snapshots the
quantity, runs the compensating operation, snapshots it again, and then proves
the freed capacity is genuinely re-acquirable rather than merely re-labelled.
"""

from test_helpers import (
    PARTS_COORDINATOR_HEADERS,
    SERVICE_AGENT_HEADERS,
    assert_center_posture,
    assert_part_lot_counts,
    assert_timestamp_millis,
    factories,
    validate_paginated,
    validate_success,
)

# The logical clock instant every scenario below pins before building state
# (PRD §2.4: nothing in this system reads the machine's wall clock).
CLOCK_INSTANT_PREFIX = "2026-06-15T09:00:00"


def _reserved_units_on_lot(api, part_lot_id):
    """Sum `units` over the lot's reservations whose `status` is `RESERVED`."""
    rows, _meta = validate_paginated(
        api.list_parts_reservations(
            PARTS_COORDINATOR_HEADERS, part_lot_id=part_lot_id, status="RESERVED"
        )
    )
    return sum(row["units"] for row in rows)


def _build_qc_passed_warranty_order_on_tight_cap(scenario):
    """A WARRANTY_REPAIR order worked to QC_PASSED at a centre capped at 30000 cents.

    The assessment prices FABRIC 120 minutes plus 4200 cents of parts, so the
    approval reserves 22390 cents against a 30000-cent ceiling; one panel unit
    is reserved and consumed and the inspection is signed by T-102, who authored
    no assessment on the claim (PRD §2.1).
    """
    scenario.set_clock()
    center = scenario.center(liability_cap_cents=30000, bench_capacity_blocks_per_day=24)
    model = scenario.model()
    panel_lot = scenario.part_lot(model["id"])
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    assessor = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("FABRIC", 3)],
    )
    inspector = scenario.technician(
        center["id"],
        employee_code="T-102",
        full_name="Dev Osei",
        certifications=[factories.certification("FABRIC", 2)],
    )
    claim = scenario.claim(center["id"], item["id"])
    scenario.submit(claim["id"])
    scenario.assess(claim["id"], assessor["id"])
    scenario.decide(claim["id"], decision_note="Warranty repair authorized.")
    order = scenario.repair_order(claim["id"])
    block = scenario.work_block(
        order["id"],
        assessor["id"],
        work_type="FABRIC",
        start_at="2026-06-16T09:00:00Z",
        end_at="2026-06-16T11:00:00Z",
    )
    reservation = scenario.reserve_parts(
        order["id"], panel_lot["id"], factories.PANEL_PART_CODE, 1
    )
    scenario.consume_parts(reservation["id"], assessor["id"])
    scenario.bench_complete(
        order["id"], assessor["id"], [factories.work_log_entry(block["id"], 120)]
    )
    scenario.qc(order["id"], inspector["id"], outcome="PASS")
    return {
        "center_id": center["id"],
        "model_id": model["id"],
        "panel_lot_id": panel_lot["id"],
        "customer_id": customer["id"],
        "item_id": item["id"],
        "assessor_id": assessor["id"],
        "inspector_id": inspector["id"],
        "claim_id": claim["id"],
        "order_id": order["id"],
    }


class TestPartsReservationReleaseRestoresLotUnits:
    """Releasing a reservation gives the reserved units back to the lot exactly."""

    def test_release_restores_the_lot_unit_triple(self, open_order):
        """Reserving 2 of 5 and releasing them returns the lot to (5, 0, 5).

        PRD §2.10: "`on_hand_units` is what is physically in the bin, `reserved_units` is the sum of `units` over reservations against the lot whose `status` is `RESERVED`, and `available_units` is `on_hand_units` minus `reserved_units`"
        PRD §3.8: "moving it `RESERVED` → `RELEASED`, stamping `settled_at`, and decreasing only the lot's `reserved_units` by `units`, so `available_units` rises by that many units while `on_hand_units` is untouched"
        PRD §3.8: "Physical units are the second conserved quantity in this system: `on_hand_units` moves only through an explicit lot adjustment or a consumption, never through a reservation or a release."

        Design: Difficulty/compensating_invariant/parts_reservation_release_restores_lot_units
        """
        scenario = open_order.scenario
        reservation = scenario.reserve_parts(
            open_order.order_id, open_order.panel_lot_id, factories.PANEL_PART_CODE, 2
        )

        before = scenario.read_lot(open_order.panel_lot_id)
        assert_part_lot_counts(before, 5, 2, 3, "AVAILABLE")

        scenario.release_parts(
            reservation["id"], reason="Panel repair replaced by a taped patch."
        )

        after = scenario.read_lot(open_order.panel_lot_id)
        assert_part_lot_counts(after, 5, 0, 5, "AVAILABLE")
        assert after["on_hand_units"] == before["on_hand_units"], (
            "a release must never move on_hand_units"
        )

    def test_released_reservation_keeps_its_settlement_audit_trail(self, open_order):
        """The settled row records RELEASED and its units, and the lot invariant closes at 0.

        PRD §3.8: "Alternatively a `PartsCoordinator` **releases** it with an optional `reason`, moving it `RESERVED` → `RELEASED`, stamping `settled_at`, and decreasing only the lot's `reserved_units` by `units`"
        PRD §2.10: "`reserved_units` is the sum of `units` over reservations against the lot whose `status` is `RESERVED`"
        PRD §2.10: "That model-level field is `SUPPORTED` when some part lot for the model has a `status` of `AVAILABLE` or `LOW`."

        Design: Difficulty/compensating_invariant/parts_reservation_release_restores_lot_units
        """
        scenario = open_order.scenario
        api = open_order.scenario.api
        reservation = scenario.reserve_parts(
            open_order.order_id, open_order.panel_lot_id, factories.PANEL_PART_CODE, 2
        )
        assert reservation["status"] == "RESERVED", reservation
        assert reservation["settled_at"] is None, reservation
        assert _reserved_units_on_lot(api, open_order.panel_lot_id) == 2
        model_before = scenario.read_model(open_order.model_id)
        assert model_before["parts_support_status"] == "SUPPORTED", model_before

        released = scenario.release_parts(
            reservation["id"], reason="Panel repair replaced by a taped patch."
        )

        assert released["status"] == "RELEASED", released
        assert released["units"] == 2, released
        assert_timestamp_millis(released["settled_at"])
        assert released["settled_at"].startswith(CLOCK_INSTANT_PREFIX), released
        assert released["part_lot_id"] == open_order.panel_lot_id, released

        reread = scenario.read_reservation(reservation["id"])
        assert reread["status"] == "RELEASED", reread
        assert reread["units"] == 2, reread

        lot = scenario.read_lot(open_order.panel_lot_id)
        assert _reserved_units_on_lot(api, open_order.panel_lot_id) == 0
        assert lot["reserved_units"] == 0, lot

        model_after = scenario.read_model(open_order.model_id)
        assert model_after["parts_support_status"] == "SUPPORTED", model_after

    def test_released_units_are_reusable_by_a_fresh_draw(self, open_order):
        """The given-back units are genuinely re-drawable: a 5-unit draw now depletes the lot.

        PRD §3.8: "`units` exceeding the lot's `available_units` is refused with `ERR_INSUFFICIENT_PART_UNITS`; a draw exactly equal to `available_units` is allowed and depletes the lot"
        PRD §2.10: "It is `DEPLETED` when `available_units` is zero"

        Design: Difficulty/compensating_invariant/parts_reservation_release_restores_lot_units
        """
        scenario = open_order.scenario
        api = open_order.scenario.api
        first = scenario.reserve_parts(
            open_order.order_id, open_order.panel_lot_id, factories.PANEL_PART_CODE, 2
        )
        scenario.release_parts(first["id"], reason="Panel repair replaced by a taped patch.")
        assert_part_lot_counts(scenario.read_lot(open_order.panel_lot_id), 5, 0, 5)

        response = api.create_parts_reservation(
            open_order.order_id,
            factories.parts_reservation_payload(
                open_order.panel_lot_id, factories.PANEL_PART_CODE, 5
            ),
            PARTS_COORDINATOR_HEADERS,
        )
        reacquired = validate_success(response, 201)

        assert reacquired["status"] == "RESERVED", reacquired
        assert reacquired["units"] == 5, reacquired
        assert_part_lot_counts(
            scenario.read_lot(open_order.panel_lot_id), 5, 5, 0, "DEPLETED"
        )
        assert _reserved_units_on_lot(api, open_order.panel_lot_id) == 5


class TestWorkBlockCancelRestoresTechnicianMinutes:
    """Cancelling booked blocks returns every scheduled minute to the technician."""

    def test_cancelling_both_blocks_returns_open_minutes_to_zero(self, open_order):
        """180 booked minutes come back 120 then 60, landing the counter on exactly 0.

        PRD §3.8: "the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`"
        PRD §3.8: "A scheduled block may be cancelled by a `ServiceAgent` or a `RepairTechnician` with an optional `reason`, moving its `status` to `CANCELLED` and decreasing the technician's `scheduled_minutes_open` by the block's `duration_minutes`, which frees the window for future conflict checks."
        PRD §3.8: "Technician minutes are a conserved quantity: every minute added to `scheduled_minutes_open` when a block is booked is given back exactly once, whether by cancellation or by completion."

        Design: Difficulty/compensating_invariant/work_block_cancel_restores_technician_minutes
        """
        scenario = open_order.scenario
        block_a = scenario.work_block(
            open_order.order_id,
            open_order.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )
        block_b = scenario.work_block(
            open_order.order_id,
            open_order.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T11:00:00Z",
            end_at="2026-06-16T12:00:00Z",
        )
        assert block_a["duration_minutes"] == 120, block_a
        assert block_b["duration_minutes"] == 60, block_b

        before = scenario.read_technician(open_order.technician_id)
        assert before["scheduled_minutes_open"] == 180, before
        assert scenario.read_order(open_order.order_id)["work_status"] == "IN_WORK"

        scenario.cancel_work_block(block_a["id"], reason="Bench reshuffled.")

        after_first = scenario.read_technician(open_order.technician_id)
        assert scenario.read_work_block(block_a["id"])["status"] == "CANCELLED"
        assert after_first["scheduled_minutes_open"] == 60, after_first

        scenario.cancel_work_block(block_b["id"], reason="Bench reshuffled.")

        after_second = scenario.read_technician(open_order.technician_id)
        assert scenario.read_work_block(block_b["id"])["status"] == "CANCELLED"
        assert after_second["scheduled_minutes_open"] == 0, after_second
        assert scenario.read_order(open_order.order_id)["work_status"] == "IN_WORK"

    def test_cancelled_blocks_never_count_as_completed_work(self, open_order):
        """The cancelled rows keep their durations and log no actual or completed minutes.

        PRD §3.8: "A scheduled block may be cancelled by a `ServiceAgent` or a `RepairTechnician` with an optional `reason`, moving its `status` to `CANCELLED` and decreasing the technician's `scheduled_minutes_open` by the block's `duration_minutes`"
        PRD §3.8: "for each block the technician's `scheduled_minutes_open` decreases by that block's `duration_minutes` while their `completed_minutes` increases by that block's `actual_minutes`"

        Design: Difficulty/compensating_invariant/work_block_cancel_restores_technician_minutes
        """
        scenario = open_order.scenario
        block_a = scenario.work_block(
            open_order.order_id,
            open_order.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )
        block_b = scenario.work_block(
            open_order.order_id,
            open_order.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T11:00:00Z",
            end_at="2026-06-16T12:00:00Z",
        )

        cancelled_a = scenario.cancel_work_block(block_a["id"], reason="Bench reshuffled.")
        cancelled_b = scenario.cancel_work_block(block_b["id"], reason="Bench reshuffled.")

        assert cancelled_a["status"] == "CANCELLED", cancelled_a
        assert cancelled_b["status"] == "CANCELLED", cancelled_b
        assert cancelled_a["duration_minutes"] == 120, cancelled_a
        assert cancelled_b["duration_minutes"] == 60, cancelled_b
        assert cancelled_a["actual_minutes"] is None, cancelled_a
        assert cancelled_b["actual_minutes"] is None, cancelled_b

        technician = scenario.read_technician(open_order.technician_id)
        assert technician["scheduled_minutes_open"] == 0, technician
        assert technician["completed_minutes"] == 0, technician

    def test_cancelled_window_is_bookable_again(self, open_order):
        """The freed 09:00-11:00 window takes a fresh block, restoring 120 open minutes.

        PRD §3.8: "must have no block already in `status` `SCHEDULED` overlapping the requested half-open interval — a conflict is refused with `ERR_TECHNICIAN_WINDOW_CONFLICT`"
        PRD §3.8: "Blocks in `CANCELLED` or `COMPLETED` never block a window."

        Design: Difficulty/compensating_invariant/work_block_cancel_restores_technician_minutes
        """
        scenario = open_order.scenario
        api = open_order.scenario.api
        block_a = scenario.work_block(
            open_order.order_id,
            open_order.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )
        block_b = scenario.work_block(
            open_order.order_id,
            open_order.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T11:00:00Z",
            end_at="2026-06-16T12:00:00Z",
        )
        scenario.cancel_work_block(block_a["id"], reason="Bench reshuffled.")
        scenario.cancel_work_block(block_b["id"], reason="Bench reshuffled.")
        assert scenario.read_technician(open_order.technician_id)[
            "scheduled_minutes_open"
        ] == 0

        payload = factories.work_block_payload(
            open_order.order_id,
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )
        payload["technician_id"] = open_order.technician_id
        rebooked = validate_success(
            api.create_work_block(payload, SERVICE_AGENT_HEADERS), 201
        )

        assert rebooked["status"] == "SCHEDULED", rebooked
        assert rebooked["duration_minutes"] == 120, rebooked
        assert rebooked["technician_id"] == open_order.technician_id, rebooked
        assert rebooked["routed_by_selector"] is False, rebooked

        technician = scenario.read_technician(open_order.technician_id)
        assert technician["scheduled_minutes_open"] == 120, technician
        assert technician["completed_minutes"] == 0, technician


class TestLiabilityEntryReleaseRestoresCenterExposure:
    """Handing the unit back releases exactly the exposure the approval reserved."""

    def test_release_to_customer_unwinds_open_exposure_to_zero(self, scenario):
        """22390 cents of open exposure at CONSTRAINED returns to 0 at OPEN on hand-back.

        PRD §2.9: "`open_liability_cents` is the sum of `reserved_amount_cents` over every liability entry whose `status` is `OPEN` and whose claim's `service_center_id` is this centre."
        PRD §2.9: "Otherwise, if `open_liability_cents` multiplied by one hundred is strictly greater than sixty multiplied by `liability_cap_cents`, the posture is `CONSTRAINED`."
        PRD §3.9: "For a warranty order the claim's open liability entry with `basis` `REPAIR` moves `OPEN` → `RELEASED` with `release_reason` `ORDER_RELEASED` and `released_at` stamped, the centre's `open_liability_cents` decreases by the released amount, and `liability_posture` is re-derived"

        Design: Difficulty/compensating_invariant/liability_entry_release_restores_center_exposure
        """
        world = _build_qc_passed_warranty_order_on_tight_cap(scenario)

        before = scenario.read_center(world["center_id"])
        assert_center_posture(before, 22390, 74.63, "CONSTRAINED")

        order = scenario.release_to_customer(world["order_id"])

        after = scenario.read_center(world["center_id"])
        assert_center_posture(after, 0, 0.00, "OPEN")
        assert after["version"] > before["version"], (after, before)

        assert order["work_status"] == "RELEASED", order
        assert order["billing_status"] == "NOT_BILLABLE", order
        assert scenario.read_claim(world["claim_id"])["status"] == "CLOSED_FULFILLED"
        assert scenario.read_item(world["item_id"])["disposition_status"] == "RETURNED"

    def test_released_entry_retains_its_reserved_amount_for_audit(self, scenario):
        """The settled entry keeps 22390 cents with ORDER_RELEASED, and the OPEN sum is 0.

        PRD §2.9: "Entries whose `status` is `RELEASED` are excluded from the sum but retain their `reserved_amount_cents` for audit."
        PRD §3.9: "the claim's open liability entry with `basis` `REPAIR` moves `OPEN` → `RELEASED` with `release_reason` `ORDER_RELEASED` and `released_at` stamped"
        PRD §3.5: "a `reserved_amount_cents` equal to the lesser of the claim's `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents`"

        Design: Difficulty/compensating_invariant/liability_entry_release_restores_center_exposure
        """
        world = _build_qc_passed_warranty_order_on_tight_cap(scenario)

        opened = scenario.liability_entries(world["claim_id"])
        assert len(opened) == 1, opened
        assert opened[0]["status"] == "OPEN", opened[0]
        assert opened[0]["reserved_amount_cents"] == 22390, opened[0]
        assert opened[0]["release_reason"] is None, opened[0]
        assert opened[0]["released_at"] is None, opened[0]

        scenario.release_to_customer(world["order_id"])

        entries = scenario.liability_entries(world["claim_id"])
        assert len(entries) == 1, entries
        entry = entries[0]
        assert entry["id"] == opened[0]["id"], (entry, opened[0])
        assert entry["basis"] == "REPAIR", entry
        assert entry["valuation_variant"] == "DEPRECIATED_PURCHASE", entry
        assert entry["status"] == "RELEASED", entry
        assert entry["release_reason"] == "ORDER_RELEASED", entry
        assert entry["reserved_amount_cents"] == 22390, entry
        assert_timestamp_millis(entry["released_at"])
        assert entry["released_at"].startswith(CLOCK_INSTANT_PREFIX), entry

        open_sum = sum(
            row["reserved_amount_cents"] for row in entries if row["status"] == "OPEN"
        )
        assert open_sum == 0, entries
        center = scenario.read_center(world["center_id"])
        assert center["open_liability_cents"] == open_sum, center

        lot = scenario.read_lot(world["panel_lot_id"])
        assert_part_lot_counts(lot, 4, 0, 4, "AVAILABLE")
        assessor = scenario.read_technician(world["assessor_id"])
        assert assessor["scheduled_minutes_open"] == 0, assessor
        assert assessor["completed_minutes"] == 120, assessor

    def test_released_headroom_is_reusable_by_a_second_approval(self, scenario):
        """The freed 22390 cents of headroom takes a second approval back to CONSTRAINED.

        PRD §2.9: "Because releases can be large, the posture may skip a band in either direction: a single release that clears the whole band moves a centre from `FROZEN` straight to `OPEN`, and it may equally move `FROZEN` to `CONSTRAINED` or `CONSTRAINED` to `OPEN`."
        PRD §2.9: "Under `FROZEN`, both warranty outcomes — repair and replacement — are refused with `ERR_CENTER_LIABILITY_FROZEN`"
        PRD §3.5: "that new open entry increases the centre's `open_liability_cents` by the reserved amount and recomputes `liability_utilization_pct`"

        Design: Difficulty/compensating_invariant/liability_entry_release_restores_center_exposure
        """
        world = _build_qc_passed_warranty_order_on_tight_cap(scenario)
        scenario.release_to_customer(world["order_id"])
        assert_center_posture(scenario.read_center(world["center_id"]), 0, 0.00, "OPEN")

        second_item = scenario.gear_item(
            world["model_id"], world["customer_id"], serial_number=factories.SERIAL_B
        )
        second_claim = scenario.claim(world["center_id"], second_item["id"])
        scenario.submit(second_claim["id"])
        scenario.assess(second_claim["id"], world["assessor_id"])
        decided = scenario.decide(
            second_claim["id"], decision_note="Second defect confirmed."
        )

        assert decided["decision"] == "WARRANTY_REPAIR", decided
        assert decided["status"] == "WARRANTY_APPROVED", decided

        entries = scenario.liability_entries(second_claim["id"])
        assert len(entries) == 1, entries
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["reserved_amount_cents"] == 22390, entries[0]

        center = scenario.read_center(world["center_id"])
        assert_center_posture(center, 22390, 74.63, "CONSTRAINED")
