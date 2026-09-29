"""Cascades that travel several links away from the request that started them.

Each chain here is caused link by link — the audit failure reaches the engines
through the family, the model and the order; the lot rejection reaches them
through the supplier and its sibling lots; and the supersession reaches the
fill-rate figures through the open backorder it re-points.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    build_allocatable_plant,
    build_certification_family,
    build_engine_platform,
    build_released_order_plant,
    build_service_part,
    get_success_data,
    inspect_component_lot,
    raise_parts_request,
    read_build_order,
    read_engine_unit,
    read_family,
    read_lot,
    read_model,
    read_platform,
    read_service_part,
    read_supplier_scorecard,
    receive_component_lot,
    record_line_audit,
    run_allocations,
    schedule_line_audit,
    stage_engine_unit,
    supersede_service_part,
)

AUDIT_WEEK = "2026-09-14"


def _allocated_plant_with_one_unit_still_on_the_line():
    """Two released and allocated units plus a third unit still staged."""
    scenario = build_allocatable_plant(released_units=2)
    allocated = run_allocations(scenario.build_order_id)
    assert allocated["allocated_dealer_units"] == 1
    assert allocated["allocated_mass_retail_units"] == 1
    assert allocated["unallocated_units"] == 0
    stage_engine_unit(scenario, "SN-0003")
    return scenario


def _fail_the_audit(order_id):
    audit = schedule_line_audit(order_id, audit_week=AUDIT_WEEK)
    assert audit["required_sample_size"] == 2
    return record_line_audit(
        audit["id"],
        units_tested=2,
        units_failed=2,
        max_measured_emission_g_per_kwh=5.60,
    )


def _plant_with_a_staged_unit_and_a_second_carburetor_lot():
    """One engine staged from CB-001, and CB-002 waiting for inspection."""
    scenario = build_released_order_plant()
    staged = stage_engine_unit(scenario, "SN-0001")
    second_lot = receive_component_lot(
        scenario.suppliers["carburetor"]["id"], lot_code="CB-002", lot_quantity=200
    )
    return scenario, staged, second_lot


def _requests_of(part_id):
    rows = get_success_data(
        api_client.list_service_part_requests(
            part_id, TEST_USERS["plant_admin_headers"]
        )
    )
    return {row["id"]: row for row in rows}


class TestAuditFailureCascade:
    """One recorded audit result reaches the engines five links away."""

    def test_the_failed_audit_puts_the_family_on_hold(self, canonical_clock):
        """PRD §3.8: "`failure_rate` is `units_failed` divided by `units_tested`, rounded half up to 4 decimal places."
        PRD §3.8: "Otherwise, when a rate breach holds, the audit is `FAILED` with `failure_reason` `FAILURE_RATE_EXCEEDED`."
        PRD §3.8: "If the resulting count is still below 2, the family moves to `AUDIT_HOLD` and its `audit_hold_at` is stamped from the clock."

        Design: Difficulty/transitive_cascade/audit_failure_five_level_family_cascade
        """
        scenario = _allocated_plant_with_one_unit_still_on_the_line()

        recorded = _fail_the_audit(scenario.build_order_id)

        assert recorded["status"] == "FAILED"
        assert recorded["failure_rate"] == pytest.approx(1.0000, abs=0.00005)
        assert recorded["failure_reason"] == "FAILURE_RATE_EXCEEDED"
        assert recorded["recorded_by_user_id"] == "co-ravi"

        family = read_family(scenario.family_id)
        assert family["status"] == "AUDIT_HOLD"
        assert family["cumulative_audit_failures"] == 1
        assert family["audit_hold_at"].startswith("2026-08-03T08:00:00")

    def test_the_hold_travels_through_the_platform_and_model_to_the_order(
        self, canonical_clock
    ):
        """PRD §3.8: "Every engine platform of that family has its `certification_posture` recomputed by the projection of §2.7, landing on `RESTRICTED` for an `AUDIT_HOLD` family and on the terminal `FROZEN` for a `SUSPENDED` one."
        PRD §3.8: "Every product model sitting on those platforms whose `status` is `RELEASED` moves to `SUSPENDED`, which blocks new build orders against it."
        PRD §3.8: "Every build order of those models whose status is `PLANNED`, `RELEASED` or `IN_PRODUCTION` moves to `HELD`, with its prior status captured in `status_before_hold` and `held_reason` set to `FAMILY_AUDIT_HOLD`."

        Design: Difficulty/transitive_cascade/audit_failure_five_level_family_cascade
        """
        scenario = _allocated_plant_with_one_unit_still_on_the_line()
        assert read_build_order(scenario.build_order_id)["status"] == "IN_PRODUCTION"

        _fail_the_audit(scenario.build_order_id)

        assert (
            read_platform(scenario.platform_id)["certification_posture"] == "RESTRICTED"
        )
        assert read_model(scenario.model_id)["status"] == "SUSPENDED"

        order = read_build_order(scenario.build_order_id)
        assert order["status"] == "HELD"
        assert order["status_before_hold"] == "IN_PRODUCTION"
        assert order["held_reason"] == "FAMILY_AUDIT_HOLD"

    def test_the_held_order_quarantines_its_line_units_and_tears_up_the_split(
        self, canonical_clock
    ):
        """PRD §3.8: "For every order newly moved to `HELD`, every engine unit whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED` has its `conformance_state` moved to `QUARANTINED`, its `build_state` left exactly where it was."
        PRD §3.8: "For every order newly moved to `HELD`, `allocated_dealer_units` and `allocated_mass_retail_units` are reset to 0, `unallocated_units` is set to the full `built_quantity`, and `allocation_status` returns to `UNALLOCATED` — the standing channel position is torn up because the goods can no longer be shipped."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."

        Design: Difficulty/transitive_cascade/audit_failure_five_level_family_cascade
        """
        scenario = _allocated_plant_with_one_unit_still_on_the_line()
        released_ids = [unit["id"] for unit in scenario.units[:2]]
        staged_id = scenario.units[2]["id"]

        _fail_the_audit(scenario.build_order_id)

        on_the_line = read_engine_unit(staged_id)
        assert on_the_line["conformance_state"] == "QUARANTINED"
        assert on_the_line["build_state"] == "STAGED"

        for unit_id in released_ids:
            finished = read_engine_unit(unit_id)
            assert finished["conformance_state"] == "CONFORMING"
            assert finished["build_state"] == "RELEASED"

        order = read_build_order(scenario.build_order_id)
        assert order["allocated_dealer_units"] == 0
        assert order["allocated_mass_retail_units"] == 0
        assert order["unallocated_units"] == 2
        assert order["allocation_status"] == "UNALLOCATED"
        assert order["built_quantity"] == 2
        assert order["staged_quantity"] == 1


class TestLotRejectionCascade:
    """One rejected sample reaches the engines through the supplier."""

    def test_the_rejection_re_pools_the_supplier_onto_probation(self, canonical_clock):
        """PRD §3.4: "A rejection sets `accepted_qty` to 0 and `remaining_qty` to 0, writes `defect_ppm` in exactly the same way, records `inspected_by_user_id` in exactly the same way, adds 1 to the supplier's `inspected_lot_count`, **resets** the supplier's `consecutive_accepted_lots` to 0, and recomputes `rolling_defect_ppm`."
        PRD §3.4: "Otherwise: if the recomputed pooled rate is **greater than** 100,000 parts per million, the supplier becomes `SUSPENDED` and its `incoming_inspection_level` becomes `TIGHTENED`; else if the pooled rate is **greater than** 25,000 parts per million, the supplier becomes `PROBATION` and its level becomes `TIGHTENED`; else the supplier becomes `APPROVED` and its level is chosen from the accepted-lot streak — `SKIP_LOT` when `consecutive_accepted_lots` is at least 5, `REDUCED` when it is at least 3, and `NORMAL` otherwise."

        Design: Difficulty/transitive_cascade/lot_rejection_supplier_probation_quarantine_cascade
        """
        scenario, _, second_lot = _plant_with_a_staged_unit_and_a_second_carburetor_lot()
        assert second_lot["sample_size"] == 10
        assert second_lot["acceptance_number"] == 1

        rejected = inspect_component_lot(second_lot["id"], defects_found=2)

        assert rejected["status"] == "REJECTED"
        assert rejected["defect_ppm"] == 200000
        assert rejected["accepted_qty"] == 0
        assert rejected["remaining_qty"] == 0

        scorecard = read_supplier_scorecard(scenario.suppliers["carburetor"]["id"])
        assert scorecard["rolling_defect_ppm"] == 40000
        assert scorecard["approval_status"] == "PROBATION"
        assert scorecard["incoming_inspection_level"] == "TIGHTENED"
        assert scorecard["consecutive_accepted_lots"] == 0
        assert scorecard["inspected_lot_count"] == 2

    def test_probation_quarantines_the_sibling_lot_and_the_engine_built_from_it(
        self, canonical_clock
    ):
        """PRD §3.4: "The moment an inspection pushes a supplier from `APPROVED` onto `PROBATION`, or onto `SUSPENDED` from either `APPROVED` or `PROBATION`, three further effects fire in order."
        PRD §3.4: "Then **every other lot of that same supplier** whose status is `RECEIVED` or `ACCEPTED` and whose `remaining_qty` is greater than zero moves to `QUARANTINED`; a quarantined lot can no longer be inspected, and any attempt is refused with `ERR_LOT_STATE_INVALID`, while any attempt to stage a unit from it is refused with `ERR_COMPONENT_LOT_NOT_RELEASABLE`."
        PRD §3.4: "Finally, every engine unit whose `build_state` is `STAGED` and whose `carburetor_lot_id` or `ignition_lot_id` is one of those newly quarantined lots has its `conformance_state` moved to `QUARANTINED`, its `build_state` left exactly where it was."

        Design: Difficulty/transitive_cascade/lot_rejection_supplier_probation_quarantine_cascade
        """
        scenario, staged, second_lot = (
            _plant_with_a_staged_unit_and_a_second_carburetor_lot()
        )

        inspect_component_lot(second_lot["id"], defects_found=2)

        sibling = read_lot(scenario.carburetor_lot_id)
        assert sibling["status"] == "QUARANTINED"
        assert sibling["consumed_qty"] == 1
        assert sibling["remaining_qty"] == 799

        unit = read_engine_unit(staged["id"])
        assert unit["conformance_state"] == "QUARANTINED"
        assert unit["build_state"] == "STAGED"

        order = read_build_order(scenario.build_order_id)
        assert order["staged_quantity"] == 1
        assert order["built_quantity"] == 0

    def test_the_quarantine_sweep_stays_inside_the_offending_supplier(
        self, canonical_clock
    ):
        """PRD §3.4: "The population is every lot of that supplier whose status is `ACCEPTED`, `REJECTED` or `DEVIATION_ACCEPTED` **and** whose `sample_size` is greater than zero; lots still `RECEIVED`, lots `QUARANTINED`, and lots that were waved through at `SKIP_LOT` with a sample size of zero are excluded."
        PRD §2.11: "Staging an engine unit charges one piece to each of the two lots it consumes, adding 1 to each lot's `consumed_qty` and subtracting 1 from each lot's `remaining_qty`."

        Design: Difficulty/transitive_cascade/lot_rejection_supplier_probation_quarantine_cascade
        """
        scenario, _, second_lot = _plant_with_a_staged_unit_and_a_second_carburetor_lot()

        inspect_component_lot(second_lot["id"], defects_found=2)

        ignition_lot = read_lot(scenario.ignition_lot_id)
        assert ignition_lot["status"] == "ACCEPTED"
        assert ignition_lot["consumed_qty"] == 1
        assert ignition_lot["remaining_qty"] == 799
        assert read_lot(scenario.casting_lot_id)["status"] == "ACCEPTED"

        for category in ("ignition", "casting"):
            other = read_supplier_scorecard(scenario.suppliers[category]["id"])
            assert other["approval_status"] == "APPROVED"
            assert other["incoming_inspection_level"] == "NORMAL"


class TestSupersessionCascade:
    """Superseding a part re-points its backorder and re-derives both fill rates."""

    def test_supersession_substitutes_the_open_backorder_from_successor_stock(
        self, canonical_clock
    ):
        """PRD §3.9: "The part moves `ACTIVE → SUPERSEDED` and its `superseded_by_part_id` is set to the successor."
        PRD §3.9: "Then the part's open backorders are worked off from the successor's stock, in strict `created_at` ascending order with no fallback ordering by identifier: for each such request in turn, if the successor's `on_hand_qty` at that moment is at least the request's `requested_quantity`, the request becomes `SUBSTITUTED`, its `shipped_from_part_id` is set to the successor, the successor's `on_hand_qty` is reduced by `requested_quantity`, and its `promised_ship_date` is recomputed from the clock date and the successor's lead time for that request's `channel`."
        PRD §3.9: "A request left `BACKORDERED` gets `promised_ship_date` equal to the clock date plus 21 days."

        Design: Difficulty/transitive_cascade/supersede_backorder_substitution_fill_rate_cascade
        """
        family = build_certification_family()
        platform = build_engine_platform(family["id"])
        predecessor = build_service_part(
            platform["id"], part_number="PN-CARB-KIT-1", on_hand_qty=1
        )
        successor = build_service_part(
            platform["id"], part_number="PN-CARB-KIT-2", on_hand_qty=5
        )

        filled = raise_parts_request(predecessor["id"], requested_quantity=1)
        assert filled["status"] == "FILLED"
        backordered = raise_parts_request(predecessor["id"], requested_quantity=1)
        assert backordered["status"] == "BACKORDERED"
        assert backordered["promised_ship_date"] == "2026-08-24"

        superseded = supersede_service_part(predecessor["id"], successor["id"])

        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_part_id"] == successor["id"]

        substituted = _requests_of(predecessor["id"])[backordered["id"]]
        assert substituted["status"] == "SUBSTITUTED"
        assert substituted["shipped_from_part_id"] == successor["id"]
        assert substituted["promised_ship_date"] == "2026-08-05"
        assert read_service_part(successor["id"])["on_hand_qty"] == 4

    def test_both_parts_re_derive_their_counters_and_fill_rate(self, canonical_clock):
        """PRD §3.9: "Finally, the counters and `fill_rate_pct` are recomputed on **both** parts: the superseded predecessor and the successor."
        PRD §3.9: "Requests are attributed to a part by where the pieces came from: a `FILLED` or `SUBSTITUTED` request counts against its `shipped_from_part_id`, while a `BACKORDERED` request counts against its `service_part_id`."
        PRD §3.9: "Otherwise it is the served count divided by the total, multiplied by 100, rounded half up to 2 decimal places."

        Design: Difficulty/transitive_cascade/supersede_backorder_substitution_fill_rate_cascade
        """
        family = build_certification_family()
        platform = build_engine_platform(family["id"])
        predecessor = build_service_part(
            platform["id"], part_number="PN-CARB-KIT-1", on_hand_qty=1
        )
        successor = build_service_part(
            platform["id"], part_number="PN-CARB-KIT-2", on_hand_qty=5
        )
        filled = raise_parts_request(predecessor["id"], requested_quantity=1)
        raise_parts_request(predecessor["id"], requested_quantity=1)

        supersede_service_part(predecessor["id"], successor["id"])

        left_behind = read_service_part(predecessor["id"])
        assert left_behind["filled_request_count"] == 1
        assert left_behind["substituted_request_count"] == 0
        assert left_behind["backordered_request_count"] == 0
        assert left_behind["fill_rate_pct"] == pytest.approx(100.00, abs=0.005)
        assert left_behind["on_hand_qty"] == 0

        taking_over = read_service_part(successor["id"])
        assert taking_over["substituted_request_count"] == 1
        assert taking_over["filled_request_count"] == 0
        assert taking_over["backordered_request_count"] == 0
        assert taking_over["fill_rate_pct"] == pytest.approx(100.00, abs=0.005)

        # The request settled before the supersession is left exactly as it was.
        untouched = _requests_of(predecessor["id"])[filled["id"]]
        assert untouched["status"] == "FILLED"
        assert untouched["shipped_from_part_id"] == predecessor["id"]
        assert untouched["promised_ship_date"] == "2026-08-05"
