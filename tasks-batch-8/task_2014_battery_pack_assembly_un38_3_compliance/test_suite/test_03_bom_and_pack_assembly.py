"""BOM definition, pack assembly, OCC on BOM version, and parallel state axes."""
import re

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_version_incremented,
    attach_pack,
    carrier_accept_shipment,
    create_accepted_cell_lot,
    create_battery_pack,
    create_battery_pack_payload,
    create_pack_bom,
    create_pack_bom_payload,
    create_program,
    create_shipment,
    create_storage_location,
    get_battery_pack,
    get_pack_bom,
    get_shipment,
    make_any_headers,
    mark_delivered,
    mark_in_transit,
    pick_pack,
    setup_program_with_bom,
    setup_ready_to_store_pack,
    stage_pack,
    stage_store_pick_pack,
    store_placement,
    tender_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPackBomCreation:
    def test_nominal_energy_computed_at_creation(self, api):
        """PRD §3.3: "The BOM's `nominal_energy_wh` is computed at creation as the
        `cells_required` multiplied by the lot's `rated_capacity_mah`, multiplied by the
        nominal 3.6 volts per cell, and divided by 1000, rounded half-up to two decimal
        places."

        Design: Corner/entities/pack_bom_nominal_energy_computed
        """
        program = create_program()
        lot = create_accepted_cell_lot(program["id"])  # 3000 mAh cells
        resp = api.create_pack_bom(
            program["id"],
            create_pack_bom_payload(lot["id"], cells_required=4),
            TEST_USERS["assembly_lead_headers"],
        )
        bom = validate_success(resp, 201)
        # 4 * 3000 * 3.6 / 1000 = 43.20
        assert bom["nominal_energy_wh"] == pytest.approx(43.20)
        assert bom["is_locked"] is False

    def test_invalid_welding_profile_enum_rejected(self, api):
        """PRD §2.12: "an enum field carrying a value outside its declared set is rejected
        with `ERR_INVALID_ENUM`".
        PRD §3.3: "a `welding_profile` of `WELD_PROFILE_A`, `WELD_PROFILE_B`, or
        `WELD_PROFILE_C` selecting the base heat dose for welding".

        Design: Corner/entities/enum_field_rejects_invalid_value
        """
        program = create_program()
        lot = create_accepted_cell_lot(program["id"])
        resp = api.create_pack_bom(
            program["id"],
            create_pack_bom_payload(lot["id"], welding_profile="WELD_PROFILE_XYZ"),
            TEST_USERS["assembly_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_bom_rejected_when_lot_in_quarantine(self, api):
        """PRD §3.3: "The referenced lot must belong to the same program (otherwise
        `ERR_CROSS_PROGRAM_REFERENCE`), must be `ACCEPTED` (otherwise
        `ERR_LOT_NOT_ACCEPTED`)".

        Design: Difficulty/cross_entity_state_dependency/pack_bom_creation_gated_on_celllot_accepted
        """
        program = create_program()
        headers = TEST_USERS["quality_engineer_headers"]
        lot = validate_success(
            api.create_cell_lot(
                program["id"],
                {"lot_code": "LOT-M", "cell_count": 100, "rated_capacity_mah": 3000,
                 "receiving_soc_percent": 40.0},
                headers,
            ),
            201,
        )
        validate_success(api.quarantine_cell_lot(program["id"], lot["id"], headers))
        resp = api.create_pack_bom(
            program["id"],
            create_pack_bom_payload(lot["id"]),
            TEST_USERS["assembly_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACCEPTED)
        lot_after = validate_success(api.get_cell_lot(program["id"], lot["id"], TEST_USERS["any_headers"]))
        assert lot_after["status"] == "QUARANTINE"

    def test_bom_rejected_when_lot_only_received(self, api):
        """PRD §3.3: "The referenced lot must belong to the same program (otherwise
        `ERR_CROSS_PROGRAM_REFERENCE`), must be `ACCEPTED` (otherwise
        `ERR_LOT_NOT_ACCEPTED`)". A lot still in its born `RECEIVED` state has not been
        accepted, so the BOM definition is refused identically.

        Design: Difficulty/cross_entity_state_dependency/pack_bom_creation_gated_on_celllot_accepted
        """
        program = create_program()
        lot = validate_success(
            api.create_cell_lot(
                program["id"],
                {"lot_code": "LOT-R", "cell_count": 100, "rated_capacity_mah": 3000,
                 "receiving_soc_percent": 40.0},
                TEST_USERS["quality_engineer_headers"],
            ),
            201,
        )
        assert lot["status"] == "RECEIVED"
        resp = api.create_pack_bom(
            program["id"],
            create_pack_bom_payload(lot["id"]),
            TEST_USERS["assembly_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACCEPTED)

    def test_bom_rejected_when_lot_belongs_to_other_program(self, api):
        """PRD §2.5: "Whenever a child-creating call references another resource — a lot,
        a BOM, a firmware row, a storage location, a shipment — that referenced resource
        must belong to the same program as the path's `{programId}`; otherwise the call is
        rejected with `ERR_CROSS_PROGRAM_REFERENCE`."

        Design: Corner/validations/cross_program_reference_rejected
        """
        program_a = create_program()
        program_b = create_program()
        lot_b = create_accepted_cell_lot(program_b["id"])
        resp = api.create_pack_bom(
            program_a["id"],
            create_pack_bom_payload(lot_b["id"]),
            TEST_USERS["assembly_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)


class TestPackAssembly:
    def test_serial_number_format(self, api):
        """PRD §3.3: "The new pack receives a `serial_number` in the form SN- followed by
        the program's `program_code`, a dash, and a zero-padded six-digit counter".

        Design: Corner/entities/battery_pack_serial_number_format
        """
        bundle = setup_program_with_bom(program_code="PRG-Z5")
        pack = create_battery_pack(bundle["program"]["id"], bundle["bom"]["id"])
        assert re.fullmatch(r"SN-PRG-Z5-[0-9]{6}", pack["serial_number"]), (
            f"serial_number {pack['serial_number']!r} does not match SN-<program_code>-NNNNNN"
        )
        assert pack["assembly_status"] == "BUILT"
        assert pack["logistics_status"] == "NOT_STORED"
        assert pack["disposition"] == "IN_SERVICE"

    def test_stale_bom_version_rejected_412(self, api):
        """PRD §2.10: "If the BOM's current `version` does not match — for example because
        another pack assembly has consumed the BOM in the meantime and advanced it — the
        creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_bom_version_rejected_412
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        bom = bundle["bom"]
        stale_version = bom["version"]
        create_battery_pack(program_id, bom["id"])  # advances BOM version past the capture
        resp = api.create_battery_pack(
            program_id,
            create_battery_pack_payload(bom["id"], stale_version),
            TEST_USERS["assembly_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_correct_bom_version_succeeds_and_locks_bom(self, api):
        """PRD §2.10: "Assembling a pack requires the request to carry
        `expected_bom_version`, the `version` of the `PackBOM` as the client last observed
        it."
        PRD §3.3: "Consuming the BOM flips its `is_locked` to true and increments the
        BOM's `version` by 1".

        Design: Corner/complexity_layers/occ_correct_version_succeeds
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        bom = bundle["bom"]
        resp = api.create_battery_pack(
            program_id,
            create_battery_pack_payload(bom["id"], bom["version"]),
            TEST_USERS["assembly_lead_headers"],
        )
        pack = validate_success(resp, 201)
        assert pack["bom_id"] == bom["id"]
        bom_after = get_pack_bom(program_id, bom["id"])
        assert_version_incremented(bom_after["version"], bom["version"])
        assert bom_after["version"] == bom["version"] + 1
        assert bom_after["is_locked"] is True

    def test_flat_pack_list_filters_by_bom_id(self, api):
        """PRD §2.5: "The flat list routes accept the standard pagination parameters plus
        optional equality filters mirroring the entity's foreign keys: `program_id`,
        `cell_lot_id`, `bom_id`".

        Design: Corner/endpoints/get_pack_list_supports_bom_id_filter
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        lot_id = bundle["lot"]["id"]
        bom_a = bundle["bom"]
        bom_b = create_pack_bom(program_id, lot_id, bom_code="BOM-B")
        pack_a = create_battery_pack(program_id, bom_a["id"])
        create_battery_pack(program_id, bom_b["id"])

        resp = api.list_battery_packs_flat(make_any_headers(), params={"bom_id": bom_a["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected exactly one pack for bom_id filter, got {len(data)}"
        assert data[0]["id"] == pack_a["id"]
        assert data[0]["bom_id"] == bom_a["id"]


class TestParallelAxes:
    def test_assembly_axis_frozen_while_logistics_runs_to_delivered(self, api):
        """PRD §3.3: "In parallel and independently, the logistics axis runs `NOT_STORED`
        → `STAGED` → `STORED` → `PICKED` → `PACKED_FOR_SHIP` → `SHIPPED` → `DELIVERED` →
        `RETURNED`, governed by §3.7 through §3.9."
        PRD §3.8: "Final delivery requires `IN_TRANSIT` (`ERR_SHIPMENT_NOT_IN_TRANSIT`),
        moves the shipment to its terminal `DELIVERED` state, cascades every attached pack
        from `SHIPPED` to `DELIVERED`, and sets each delivered pack's `disposition` to
        `IN_SERVICE`."

        Design: Difficulty/non_linear_state_machine/battery_pack_parallel_axes_independent_progression
        """
        bundle = setup_ready_to_store_pack()
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        assert bundle["pack"]["assembly_status"] == "READY_TO_STORE"
        assert bundle["pack"]["logistics_status"] == "NOT_STORED"

        stage_store_pick_pack(program_id, pack_id)
        shipment = create_shipment(program_id, un_class_code="UN3480", declared_weight_kg=5.00)
        attach_pack(program_id, shipment["id"], pack_id)
        tender_shipment(program_id, shipment["id"])
        carrier_accept_shipment(program_id, shipment["id"])
        mark_in_transit(program_id, shipment["id"])
        mark_delivered(program_id, shipment["id"])

        pack = get_battery_pack(program_id, pack_id)
        assert pack["assembly_status"] == "READY_TO_STORE"
        assert pack["logistics_status"] == "DELIVERED"
        assert pack["disposition"] == "IN_SERVICE"
        assert get_shipment(program_id, shipment["id"])["status"] == "DELIVERED"

    def test_assembly_axis_unchanged_across_stage_store_pick(self, api):
        """PRD §3.3: "In parallel and independently, the logistics axis runs `NOT_STORED`
        → `STAGED` → `STORED` → `PICKED` → `PACKED_FOR_SHIP` → `SHIPPED` → `DELIVERED` →
        `RETURNED`, governed by §3.7 through §3.9. The two axes meet at join points: a
        pack cannot be staged until its assembly axis reaches `READY_TO_STORE`".

        Design: Difficulty/non_linear_state_machine/battery_pack_parallel_axes_independent_progression
        """
        bundle = setup_ready_to_store_pack()
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]

        location = create_storage_location(program_id, accepts_soc_band=["SOC_MID"])
        stage_pack(program_id, location["id"], pack_id)
        pack = get_battery_pack(program_id, pack_id)
        assert pack["logistics_status"] == "STAGED"
        assert pack["assembly_status"] == "READY_TO_STORE"

        placements = validate_paginated(
            api.list_storage_placements(program_id, make_any_headers(), params={"battery_pack_id": pack_id})
        )[0]
        store_placement(program_id, placements[0]["id"])
        pack = get_battery_pack(program_id, pack_id)
        assert pack["logistics_status"] == "STORED"
        assert pack["assembly_status"] == "READY_TO_STORE"

        pick_pack(program_id, pack_id)
        pack = get_battery_pack(program_id, pack_id)
        assert pack["logistics_status"] == "PICKED"
        assert pack["assembly_status"] == "READY_TO_STORE"
