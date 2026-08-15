"""SOC band boundaries, storage-slot aggregate capacity, and watt-hour ledger invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_battery_pack,
    create_storage_location,
    create_storage_placement_payload,
    drive_pack_to_ready_to_store,
    get_battery_pack,
    get_program,
    get_storage_location,
    release_placement,
    setup_program_with_bom,
    setup_ready_to_store_pack,
    stage_pack,
    validate_error,
    validate_success,
)


class TestSocBandBoundary:
    def test_exactly_30_is_soc_mid(self, api):
        """PRD §3.7: "A pack's `soc_band` derives from its `soc_percent`: strictly below
        30.0 places it in `SOC_LOW`, at least 30.0 and at most 60.0 places it in
        `SOC_MID`, and above 60.0 places it in `SOC_HIGH`."

        Design: Difficulty/boundary_precision_check/soc_band_low_mid_boundary_at_exactly_30
        """
        bundle = setup_program_with_bom(soc_percent=30.0)
        pack = create_battery_pack(bundle["program"]["id"], bundle["bom"]["id"])
        assert pack["soc_percent"] == pytest.approx(30.0)
        assert pack["soc_band"] == "SOC_MID"

    def test_just_below_30_is_soc_low(self, api):
        """PRD §3.7: "A pack's `soc_band` derives from its `soc_percent`: strictly below
        30.0 places it in `SOC_LOW`, at least 30.0 and at most 60.0 places it in
        `SOC_MID`, and above 60.0 places it in `SOC_HIGH`."

        Design: Difficulty/boundary_precision_check/soc_band_low_mid_boundary_at_exactly_30
        """
        bundle = setup_program_with_bom(soc_percent=29.9)
        pack = create_battery_pack(bundle["program"]["id"], bundle["bom"]["id"])
        assert pack["soc_percent"] == pytest.approx(29.9)
        assert pack["soc_band"] == "SOC_LOW"


class TestSlotAggregateCapacity:
    def _two_ready_packs_on_one_bom(self, api):
        """Two READY_TO_STORE packs (43.20 Wh each) built from the same BOM."""
        bundle = setup_program_with_bom(storage_capacity_wh=5000)
        program_id = bundle["program"]["id"]
        first = drive_pack_to_ready_to_store(program_id, bundle["bom"])
        second = drive_pack_to_ready_to_store(program_id, bundle["bom"], firmware=first["firmware"])
        return program_id, first["pack"], second["pack"]

    def test_second_pack_rejected_when_slot_would_overflow(self, api):
        """PRD §3.7: "the slot's `wh_headroom` must be at least the pack's
        `pack_energy_wh` (`ERR_LOCATION_CAPACITY_EXCEEDED`)". An 80 Wh slot holding one
        43.20 Wh pack has 36.80 Wh of headroom, so a second 43.20 Wh pack is refused.

        Design: Difficulty/resource_temporal_overlap/storage_slot_capacity_aggregate_overlap
        """
        program_id, pack1, pack2 = self._two_ready_packs_on_one_bom(api)
        location = create_storage_location(
            program_id, capacity_wh=80, accepts_soc_band=["SOC_MID"]
        )
        stage_pack(program_id, location["id"], pack1["id"])
        resp = api.create_storage_placement(
            program_id,
            create_storage_placement_payload(location["id"], pack2["id"]),
            TEST_USERS["logistics_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOCATION_CAPACITY_EXCEEDED)

    def test_rejected_second_pack_leaves_occupancy_and_state_untouched(self, api):
        """PRD §2.8: "Staging a pack increases both `wh_occupied` on the slot and
        `wh_committed` on the program by the pack's energy; picking, releasing, or recall
        force-release decreases both by the same amount." A refused placement mutates
        nothing: the slot still shows only the first pack's energy and the second pack is
        still `NOT_STORED`.

        Design: Difficulty/resource_temporal_overlap/storage_slot_capacity_aggregate_overlap
        """
        program_id, pack1, pack2 = self._two_ready_packs_on_one_bom(api)
        location = create_storage_location(
            program_id, capacity_wh=80, accepts_soc_band=["SOC_MID"]
        )
        stage_pack(program_id, location["id"], pack1["id"])
        resp = api.create_storage_placement(
            program_id,
            create_storage_placement_payload(location["id"], pack2["id"]),
            TEST_USERS["logistics_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOCATION_CAPACITY_EXCEEDED)
        location_after = get_storage_location(program_id, location["id"])
        assert location_after["wh_occupied"] == pytest.approx(43.20)
        assert location_after["wh_headroom"] == pytest.approx(36.80)
        assert get_battery_pack(program_id, pack2["id"])["logistics_status"] == "NOT_STORED"
        assert get_program(program_id)["wh_committed"] == pytest.approx(43.20)


class TestWattHourLedgerInvariant:
    def test_stage_then_release_returns_ledgers_to_zero(self, api):
        """PRD §2.8: "Staging a pack increases both `wh_occupied` on the slot and
        `wh_committed` on the program by the pack's energy; picking, releasing, or recall
        force-release decreases both by the same amount."
        PRD §3.7: "A placement can also be released manually without a pick — the same
        recall guard applies (`ERR_PACK_UNDER_RECALL`) — which releases the placement,
        decrements the same two watt-hour ledgers, clears `storage_location_id`, and
        returns the pack's logistics axis to `NOT_STORED`."

        Design: Difficulty/compensating_invariant/storage_wh_invariant_stage_then_release_returns_to_zero
        """
        bundle = setup_ready_to_store_pack(storage_capacity_wh=10000)
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        location = create_storage_location(
            program_id, capacity_wh=5000, accepts_soc_band=["SOC_MID"]
        )
        placement = stage_pack(program_id, location["id"], pack_id)
        assert get_storage_location(program_id, location["id"])["wh_occupied"] == pytest.approx(43.20)
        assert get_program(program_id)["wh_committed"] == pytest.approx(43.20)

        released = release_placement(program_id, placement["id"])
        assert released["status"] == "RELEASED"
        assert get_storage_location(program_id, location["id"])["wh_occupied"] == pytest.approx(0)
        assert get_program(program_id)["wh_committed"] == pytest.approx(0)

    def test_release_restores_pack_to_not_stored(self, api):
        """PRD §3.7: "A placement can also be released manually without a pick — the same
        recall guard applies (`ERR_PACK_UNDER_RECALL`) — which releases the placement,
        decrements the same two watt-hour ledgers, clears `storage_location_id`, and
        returns the pack's logistics axis to `NOT_STORED`."

        Design: Difficulty/compensating_invariant/storage_wh_invariant_stage_then_release_returns_to_zero
        """
        bundle = setup_ready_to_store_pack(storage_capacity_wh=10000)
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        location = create_storage_location(
            program_id, capacity_wh=5000, accepts_soc_band=["SOC_MID"]
        )
        placement = stage_pack(program_id, location["id"], pack_id)
        release_placement(program_id, placement["id"])

        placement_after = validate_success(
            api.get_storage_placement(program_id, placement["id"], TEST_USERS["any_headers"])
        )
        assert placement_after["status"] == "RELEASED"
        assert placement_after["released_at_utc"] is not None
        pack_after = get_battery_pack(program_id, pack_id)
        assert pack_after["logistics_status"] == "NOT_STORED"
        assert pack_after["storage_location_id"] is None
