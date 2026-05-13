"""Cross-region transfers and the three-hop cascade.

PRD §3.8 governs the TransferOrder state machine and its cascade on
COMPLETE: hop 1 (bikes to ON_SHELF), hop 2 (destination counts), hop 3
(other PLANNED REPLENISH targeting same destination auto-cancelled).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    cancel_transfer,
    complete_transfer,
    create_transfer,
    create_transfer_payload,
    dispatch_transfer,
    get_bike,
    get_region,
    setup_region_at_posture,
    setup_transfer_cascade_three_hop,
    validate_error,
    validate_success,
    ADMIN,
    OPERATOR,
)


class TestTransferPlanKind:
    """PRD §3.8: 'It is REPLENISH if the destination region's
    density_posture is LOW at plan time, CLEARANCE if the source
    region's density_posture is HIGH at plan time, and if neither
    holds the plan is rejected.'"""

    def test_replenish_inferred_when_destination_low(self, api):
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=10,
            available_count_override=5,
        )
        transfer = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        assert transfer["kind"] == "REPLENISH", (
            f"PRD §3.8: destination is LOW, kind should be REPLENISH, "
            f"got {transfer['kind']}"
        )
        assert transfer["status"] == "PLANNED"

    def test_clearance_inferred_when_source_high(self, api):
        r_high, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        r_dst, _ = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=10,
            available_count_override=5,
        )
        transfer = create_transfer(
            from_region_id=r_high["id"], to_region_id=r_dst["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        assert transfer["kind"] == "CLEARANCE", (
            f"PRD §3.8: source is HIGH, kind should be CLEARANCE, "
            f"got {transfer['kind']}"
        )

    def test_neither_low_nor_high_rejected(self, api, admin_headers):
        """PRD §3.8: 'if neither holds the plan is rejected.'"""
        r_src, src_bikes = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=10,
            available_count_override=5,
        )
        r_dst, _ = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=10,
            available_count_override=5,
        )
        resp = api.create_transfer(
            create_transfer_payload(
                from_region_id=r_src["id"], to_region_id=r_dst["id"],
                bike_ids=[src_bikes[0]["id"]],
            ),
            OPERATOR,
        )
        # PRD wording "the plan is rejected" without naming a specific
        # error_id — accept any 4xx with one of the most plausible IDs.
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_TRANSFER_KIND_MISMATCH.value,
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_VALIDATION.value,
        ])


class TestTransferDispatch:
    def test_dispatch_moves_planned_to_in_transit(self, api):
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        dispatched = dispatch_transfer(t["id"])
        assert dispatched["status"] == "IN_TRANSIT", (
            "PRD §3.8: 'the transfer advances PLANNED → IN_TRANSIT'"
        )

    def test_dispatch_off_planned_rejected(self, api, admin_headers):
        """PRD §3.8: 'The transfer must still be PLANNED (otherwise
        ERR_TRANSFER_NOT_PLANNED).'"""
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        dispatch_transfer(t["id"])
        # Second dispatch
        resp = api.dispatch_transfer(t["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_PLANNED.value, 409)


class TestTransferCompleteCascade:
    """PRD §3.8: three-hop cascade on POST /transfers/{id}/complete."""

    def test_complete_drops_bikes_at_destination(self, api):
        """PRD §3.8 hop 1: 'On success each bike's region_id is set to
        to_region_id, shelf_state to ON_SHELF, and status to AVAILABLE.'"""
        ctx = setup_transfer_cascade_three_hop()
        complete_transfer(ctx["t1"]["id"])
        for bid in ctx["t1_bike_ids"]:
            b = get_bike(bid)
            assert b["region_id"] == ctx["r_low"]["id"]
            assert b["shelf_state"] == "ON_SHELF"
            assert b["status"] == "AVAILABLE"

    def test_complete_recomputes_destination_counts(self, api):
        """PRD §3.8 hop 2: 'The destination region's counts and
        density_posture are recomputed (cascade hop 2).'"""
        ctx = setup_transfer_cascade_three_hop()
        complete_transfer(ctx["t1"]["id"])
        r_low = get_region(ctx["r_low"]["id"])
        # initial 2 + 5 delivered = 7 (low=4, high=10) → NORMAL
        assert r_low["available_count"] == 7
        assert r_low["density_posture"] == "NORMAL"

    def test_complete_cancels_other_planned_replenish_to_same_destination(
        self, api,
    ):
        """PRD §3.8 hop 3: 'if the destination region's density_posture
        flips from LOW to NORMAL or from LOW to HIGH, any other PLANNED
        TransferOrder whose to_region_id is this same destination
        region and whose kind is REPLENISH is automatically transitioned
        to CANCELLED.'"""
        ctx = setup_transfer_cascade_three_hop()
        complete_transfer(ctx["t1"]["id"])
        from test_helpers import api_client
        from prd_bench_local_runner.testing import get_success_data
        t2_after = get_success_data(api_client.get_transfer(
            ctx["t2"]["id"], ADMIN,
        ))
        assert t2_after["status"] == "CANCELLED", (
            "PRD §3.8 hop 3: other PLANNED REPLENISH targeting the same "
            "destination region is auto-cancelled when posture leaves LOW"
        )


class TestTransferCancel:
    """PRD §3.8: cancel from PLANNED is a no-op on bikes; cancel from
    IN_TRANSIT restores bikes to source."""

    def test_cancel_planned_no_bike_movement(self, api):
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        bike_before = get_bike(src_bikes[0]["id"])
        cancel_transfer(t["id"])
        bike_after = get_bike(src_bikes[0]["id"])
        assert bike_after["region_id"] == bike_before["region_id"]
        assert bike_after["shelf_state"] == bike_before["shelf_state"]

    def test_cancel_in_transit_restores_bikes_to_source(self, api):
        """PRD §3.8: 'Cancelling an IN_TRANSIT transfer restores each
        bike's region_id to from_region_id, shelf_state to ON_SHELF,
        and status to AVAILABLE.'"""
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        dispatch_transfer(t["id"])
        cancel_transfer(t["id"])
        bike = get_bike(src_bikes[0]["id"])
        assert bike["region_id"] == r_src["id"]
        assert bike["shelf_state"] == "ON_SHELF"
        assert bike["status"] == "AVAILABLE"
