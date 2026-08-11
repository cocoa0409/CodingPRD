"""Fumigation scheduling, aeration cycle, lazy clearance, and cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_bin,
    create_fumigation_payload,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_bin_with_stored_placement,
    setup_planned_shipment,
    validate_error,
    validate_success,
)


class TestFumigationScheduling:
    def test_fumigation_closed_interval_touching_start_conflicts(self, api):
        """PRD (Fumigation and the Aeration Cycle): "Unlike the dryer rule,
        touching counts: a new event whose start_at is exactly an existing
        event's effective end conflicts and must instead begin strictly later.
        Conflicting schedules are rejected with ERR_FUMIGATION_TIME_CONFLICT
        (409)."

        Design: Difficulty/resource_temporal_overlap/fumigation_closed_interval_with_aeration_buffer
        """
        bin_ = create_bin(bin_code="B-3", capacity_lbs=4000,
                          allowed_product_forms=["KERNEL"])
        fu1 = validate_success(
            api.create_fumigation(
                create_fumigation_payload(
                    bin_id=bin_["id"], start_at="2026-05-10T00:00:00Z",
                    aeration_hours=48,
                ),
                make_admin_headers(),
            ),
            expected_status=201,
        )
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.start_fumigation(fu1["id"], make_admin_headers()))
        set_clock("2026-05-12T00:00:00Z")
        aerated = validate_success(
            api.begin_aeration_fumigation(fu1["id"], make_admin_headers())
        )
        assert aerated["cleared_at"] == "2026-05-14T00:00:00Z"

        # New event starting exactly at cleared_at conflicts (closed interval).
        resp = api.create_fumigation(
            create_fumigation_payload(
                bin_id=bin_["id"], start_at="2026-05-14T00:00:00Z", aeration_hours=24,
            ),
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FUMIGATION_TIME_CONFLICT, expected_status=409)

    def test_fumigation_strictly_after_effective_end_succeeds(self, api):
        """PRD (Fumigation and the Aeration Cycle): "a new event whose
        `start_at` is exactly an existing event's effective end conflicts and
        must instead begin strictly later." and "`CLEARED` and `CANCELLED`
        events no longer occupy the bin."

        Design: Difficulty/resource_temporal_overlap/fumigation_closed_interval_with_aeration_buffer
        """
        bin_ = create_bin(bin_code="B-3", capacity_lbs=4000,
                          allowed_product_forms=["KERNEL"])
        fu1 = validate_success(
            api.create_fumigation(
                create_fumigation_payload(
                    bin_id=bin_["id"], start_at="2026-05-10T00:00:00Z",
                    aeration_hours=48,
                ),
                make_admin_headers(),
            ),
            expected_status=201,
        )
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.start_fumigation(fu1["id"], make_admin_headers()))
        set_clock("2026-05-12T00:00:00Z")
        validate_success(api.begin_aeration_fumigation(fu1["id"], make_admin_headers()))
        # cleared_at = 2026-05-14T00:00:00Z; start strictly after it.
        resp = api.create_fumigation(
            create_fumigation_payload(
                bin_id=bin_["id"], start_at="2026-05-15T00:00:00Z", aeration_hours=24,
            ),
            make_admin_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"


class TestFumigationStartCascade:
    def test_fumigation_start_blocks_planned_shipment(self, api):
        """PRD (Fumigation and the Aeration Cycle): "A successful start moves
        the event to ACTIVE and fires the fumigation cascade: the bin moves
        from AVAILABLE to FUMIGATING with its fumigation_cleared_at reset to
        null, every STORED placement in the bin moves to FUMIGATION_HOLD, and
        every PLANNED shipment whose allocations reference any of those
        placements moves to BLOCKED."

        Design: Difficulty/transitive_cascade/fumigation_start_two_hop_block
        """
        scenario = setup_planned_shipment(
            required_qty_lbs=5000, shipment_quantity=800,
            bin_capacity_lbs=4000, placement_quantity=1500,
        )
        fu = validate_success(
            api.create_fumigation(
                create_fumigation_payload(
                    bin_id=scenario["bin"]["id"],
                    start_at="2026-05-10T00:00:00Z", aeration_hours=48,
                ),
                make_admin_headers(),
            ),
            expected_status=201,
        )
        set_clock("2026-05-10T00:00:00Z")
        started = validate_success(api.start_fumigation(fu["id"], make_admin_headers()))
        assert started["status"] == "ACTIVE"

        bin_after = validate_success(
            api.get_bin(scenario["bin"]["id"], make_operator_headers())
        )
        assert bin_after["status"] == "FUMIGATING"
        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["status"] == "FUMIGATION_HOLD"
        sh_after = validate_success(
            api.get_shipment(scenario["shipment"]["id"], make_operator_headers())
        )
        assert sh_after["status"] == "BLOCKED"

    def test_fumigation_hold_precedes_shipment_block(self, api):
        """PRD (Plant-Wide Safety Cascades): "Starting a fumigation event pulls
        the bin out of service, holds every stored placement in it, and blocks
        planned shipments reserving those placements".

        Design: Difficulty/transitive_cascade/fumigation_start_two_hop_block
        """
        scenario = setup_planned_shipment(
            required_qty_lbs=5000, shipment_quantity=800,
            bin_capacity_lbs=4000, placement_quantity=1500,
        )
        fu = validate_success(
            api.create_fumigation(
                create_fumigation_payload(
                    bin_id=scenario["bin"]["id"],
                    start_at="2026-05-10T00:00:00Z", aeration_hours=48,
                ),
                make_admin_headers(),
            ),
            expected_status=201,
        )
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.start_fumigation(fu["id"], make_admin_headers()))
        # Placement is the intermediate link; without its HOLD the shipment
        # would not block.
        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["status"] == "FUMIGATION_HOLD"
        sh_after = validate_success(
            api.get_shipment(scenario["shipment"]["id"], make_operator_headers())
        )
        assert sh_after["status"] == "BLOCKED"


class TestConfirmRequiresClearBin:
    def _setup_aerating_bin_with_blocked_shipment(self, api):
        scenario = setup_planned_shipment(
            required_qty_lbs=1000, shipment_quantity=1000,
            bin_capacity_lbs=4000, placement_quantity=1500,
        )
        fu = validate_success(
            api.create_fumigation(
                create_fumigation_payload(
                    bin_id=scenario["bin"]["id"],
                    start_at="2026-05-10T00:00:00Z", aeration_hours=48,
                ),
                make_admin_headers(),
            ),
            expected_status=201,
        )
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.start_fumigation(fu["id"], make_admin_headers()))
        set_clock("2026-05-12T00:00:00Z")
        validate_success(api.begin_aeration_fumigation(fu["id"], make_admin_headers()))
        return scenario, fu

    def test_confirm_while_bin_aerating_rejected(self, api):
        """PRD (Buyer Contracts and Shipment Planning): "Confirming a `PLANNED`
        shipment delivers it: the bin must be `AVAILABLE` after lazy clearance
        (`ERR_BIN_FUMIGATION_ACTIVE` otherwise)" and "only `PLANNED` shipments
        confirm" — a shipment forced to `BLOCKED` by the cascade is not in a
        valid from-state for confirm, which draws ERR_INVALID_STATE per
        "State preconditions. The target entity is in a valid from-state for
        the requested transition."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_bin_clear_of_fumigation
        """
        scenario, _ = self._setup_aerating_bin_with_blocked_shipment(api)
        sh = validate_success(
            api.get_shipment(scenario["shipment"]["id"], make_operator_headers())
        )
        assert sh["status"] == "BLOCKED"
        resp = api.confirm_shipment(sh["id"], make_operator_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_confirm_succeeds_after_lazy_clearance(self, api):
        """PRD (The Logical Clock and Lazy Fumigation Clearance): once the clock
        reaches cleared_at "the event moves to `CLEARED`, the bin returns to
        `AVAILABLE` with `fumigation_cleared_at` reset to null, held placements
        return from `FUMIGATION_HOLD` to `STORED`, and `BLOCKED` shipments whose
        allocated placements are all stored again return to `PLANNED`."
        PRD (Buyer Contracts and Shipment Planning): "when delivered quantity
        reaches the contract's `required_qty_lbs` exactly — moves an `OPEN`
        contract to `FULFILLED`."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_bin_clear_of_fumigation
        """
        scenario, _ = self._setup_aerating_bin_with_blocked_shipment(api)
        set_clock("2026-05-15T00:00:00Z")

        bin_after = validate_success(
            api.get_bin(scenario["bin"]["id"], make_operator_headers())
        )
        assert bin_after["status"] == "AVAILABLE"
        p_after = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_after["status"] == "STORED"
        sh_after = validate_success(
            api.get_shipment(scenario["shipment"]["id"], make_operator_headers())
        )
        assert sh_after["status"] == "PLANNED"

        confirmed = validate_success(
            api.confirm_shipment(sh_after["id"], make_operator_headers())
        )
        assert confirmed["status"] == "DELIVERED"
        contract_after = validate_success(
            api.get_contract(scenario["contract"]["id"], make_operator_headers())
        )
        assert contract_after["delivered_qty_lbs"] == pytest.approx(1000, abs=0.01)
        assert contract_after["status"] == "FULFILLED"
        p_final = validate_success(
            api.get_placement(scenario["placement"]["id"], make_operator_headers())
        )
        assert p_final["remaining_lbs"] == pytest.approx(500, abs=0.01)
