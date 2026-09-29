"""The plant's two conserved ledgers and the writes that reverse them.

PRD §2.8 keeps two accounting identities that must hold after every write,
including the compensating ones: the wire mass identity on each wire lot and the
piece identity on each production lot. Two verbs compensate an earlier move —
aborting a lot still in setup hands back the wire mass its opening reserved, and
reopening a sealed pack hands back the pieces the seal took out of the lot's
available count. Each test below reads the ledger before the forward move, after
it, and again after the reversal, so a reversal that drifts by a gram or by a
piece is caught rather than absorbed.
"""

import pytest

from test_helpers import (
    assert_lot_piece_ledger,
    assert_production_lot,
    assert_versions_incremented,
    assert_wire_lot,
    assert_wire_mass_ledger,
    fixtures,
    round_half_up,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# The wire mass ledger, reversed by aborting a lot still in setup
# ---------------------------------------------------------------------------


def test_abort_heading_restores_the_wire_mass_ledger_to_its_opening_state(
    api, engineer_headers
):
    """A lot reserving 210.000 kg of a 500.000 kg coil gives every gram back when it aborts.

    PRD: "For every wire lot, the mass received from the mill equals the mass still free, plus the mass reserved by lots in setup, plus the mass already burned into blanks: `gross_mass_kg` equals `available_mass_kg` plus `reserved_mass_kg` plus `consumed_mass_kg`."

    PRD: "The abort exactly compensates the reservation made at opening: `wire_reserved_kg` is subtracted from the wire lot's `reserved_mass_kg` and added back to `available_mass_kg`, leaving the mass identity of §2.8 exactly where it was before the lot existed."

    PRD: "The lot's `version` and the wire lot's `version` each increment by 1."

    Design: Difficulty/compensating_invariant/wire_mass_ledger_restored_exactly_by_heading_abort
    """
    env = fixtures.setup_lot_in_setup(planned_pieces=10000)
    wire_id = env["wire"]["id"]
    lot_id = env["lot"]["id"]

    # 10000 planned x 20.0 g x (1 + 0.05), grams to kilograms, half up to 3 dp.
    reserved_kg = round_half_up(10000 * 20.0 * 1.05 / 1000.0, 3)
    assert reserved_kg == pytest.approx(210.0, abs=0.001), (
        f"Expected a 210.000 kg reservation, computed {reserved_kg}"
    )

    before = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert_wire_lot(before)
    assert_wire_mass_ledger(before)
    assert before["available_mass_kg"] == pytest.approx(290.0, abs=0.001), (
        f"Expected available 290.000 while the lot sits in SETUP, "
        f"got {before['available_mass_kg']}"
    )
    assert before["reserved_mass_kg"] == pytest.approx(reserved_kg, abs=0.001), (
        f"Expected reserved {reserved_kg}, got {before['reserved_mass_kg']}"
    )
    assert before["consumed_mass_kg"] == pytest.approx(0.0, abs=0.001), (
        f"Nothing was headed, so consumed must stay 0.000, "
        f"got {before['consumed_mass_kg']}"
    )
    assert before["version"] == 3, (
        f"Expected wire lot version 3 after create, release and reservation, "
        f"got {before['version']}"
    )
    assert env["lot"]["wire_reserved_kg"] == pytest.approx(reserved_kg, abs=0.001), (
        f"Expected wire_reserved_kg {reserved_kg} on the opened lot, "
        f"got {env['lot']['wire_reserved_kg']}"
    )

    aborted = validate_success(
        api.abort_heading(
            lot_id, {"reason": "WIRE_SURFACE_DEFECT_FOUND_AT_SETUP"}, engineer_headers
        )
    )
    assert_production_lot(aborted)
    assert aborted["wire_reserved_kg"] == pytest.approx(0.0, abs=0.001), (
        f"Expected wire_reserved_kg 0.000 after the abort, "
        f"got {aborted['wire_reserved_kg']}"
    )
    assert_versions_incremented(env["lot"], aborted)

    after = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert_wire_mass_ledger(after)
    assert after["available_mass_kg"] == pytest.approx(500.0, abs=0.001), (
        f"Expected available 500.000 after the abort, got {after['available_mass_kg']}"
    )
    assert after["reserved_mass_kg"] == pytest.approx(0.0, abs=0.001), (
        f"Expected reserved 0.000 after the abort, got {after['reserved_mass_kg']}"
    )
    assert after["consumed_mass_kg"] == pytest.approx(0.0, abs=0.001), (
        f"Expected consumed 0.000 after the abort, got {after['consumed_mass_kg']}"
    )
    assert after["gross_mass_kg"] == pytest.approx(500.0, abs=0.001), (
        f"The mass received from the mill never moves, got {after['gross_mass_kg']}"
    )
    assert_versions_incremented(before, after)


def test_aborted_lot_contributes_nothing_and_the_wire_can_be_reserved_again(
    api, engineer_headers
):
    """The mass an abort hands back is genuinely free: a fresh lot reserves the same 210.000 kg.

    PRD: "Aborting a lot still in setup reverses its reservation exactly, moving the reserved mass back to available and leaving the identity untouched."

    PRD: "A lot that has been aborted contributes nothing to either the reserved or the consumed side; lots in any other process state contribute their reservation or their consumption."

    PRD: "The lot's `wire_reserved_kg` drops to zero, the supplied reason is stored as `abort_reason`, and and the two state dimensions move together: the lot's `process_state` goes `SETUP → ABORTED` while its `disposition` goes `IN_PROCESS → SCRAPPED`."

    Design: Difficulty/compensating_invariant/wire_mass_ledger_restored_exactly_by_heading_abort
    """
    env = fixtures.setup_lot_in_setup(planned_pieces=10000)
    wire_id = env["wire"]["id"]

    aborted = validate_success(
        api.abort_heading(
            env["lot"]["id"],
            {"reason": "WIRE_SURFACE_DEFECT_FOUND_AT_SETUP"},
            engineer_headers,
        )
    )
    assert aborted["process_state"] == "ABORTED", (
        f"Expected process_state ABORTED, got {aborted['process_state']}"
    )
    assert aborted["disposition"] == "SCRAPPED", (
        f"Expected disposition SCRAPPED, got {aborted['disposition']}"
    )
    assert aborted["abort_reason"] == "WIRE_SURFACE_DEFECT_FOUND_AT_SETUP", (
        f"Expected the supplied reason stored as abort_reason, "
        f"got {aborted['abort_reason']!r}"
    )

    restored = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert_wire_mass_ledger(restored)
    assert restored["status"] == "RELEASED", (
        f"The coil is still on the heading floor, got status {restored['status']}"
    )
    assert restored["available_mass_kg"] == pytest.approx(500.0, abs=0.001), (
        f"Expected the full 500.000 kg free again, got {restored['available_mass_kg']}"
    )

    listed, _ = validate_paginated(
        api.list_wire_lots(engineer_headers, {"steel_heat_id": env["heat"]["id"]})
    )
    assert [row["id"] for row in listed] == [wire_id], (
        f"Expected the coil still listed under its steel heat, got {listed}"
    )
    assert listed[0]["status"] == "RELEASED", (
        f"Expected status RELEASED in the filtered list, got {listed[0]['status']}"
    )

    replacement = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2651",
        planned_pieces=10000,
        press_window_start_at="2026-09-01T10:00:00Z",
        press_window_end_at="2026-09-01T14:00:00Z",
    )
    assert replacement["wire_reserved_kg"] == pytest.approx(210.0, abs=0.001), (
        f"Expected the replacement lot to reserve 210.000 kg out of the restored "
        f"mass, got {replacement['wire_reserved_kg']}"
    )

    reused = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert_wire_mass_ledger(reused)
    assert reused["available_mass_kg"] == pytest.approx(290.0, abs=0.001), (
        f"Expected available back down to 290.000, got {reused['available_mass_kg']}"
    )
    assert reused["reserved_mass_kg"] == pytest.approx(210.0, abs=0.001), (
        f"Expected reserved 210.000 for the replacement lot, "
        f"got {reused['reserved_mass_kg']}"
    )


def test_abort_reverses_only_its_own_reservation_to_the_third_decimal(
    api, engineer_headers
):
    """Two lots share one coil; aborting the larger leaves the sibling's 13.204 kg alone.

    PRD: "The required mass is `planned_pieces` multiplied by the part's `blank_mass_g`, multiplied by one plus `scrap_allowance_pct`, divided by 1000 to convert grams to kilograms, and rounded half up to three decimal places."

    PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

    PRD: "Aborting a lot still in setup reverses its reservation exactly, moving the reserved mass back to available and leaving the identity untouched."

    Design: Difficulty/compensating_invariant/wire_mass_ledger_restored_exactly_by_heading_abort
    """
    env = fixtures.setup_master_data(
        spec_overrides={"blank_mass_g": 12.34, "scrap_allowance_pct": 0.07}
    )
    wire_id = env["wire"]["id"]

    big_reserved = round_half_up(3333 * 12.34 * 1.07 / 1000.0, 3)  # 44.008
    small_reserved = round_half_up(1000 * 12.34 * 1.07 / 1000.0, 3)  # 13.204
    assert (big_reserved, small_reserved) == (44.008, 13.204), (
        f"Expected reservations 44.008 and 13.204, "
        f"computed {big_reserved} and {small_reserved}"
    )

    big = fixtures.open_production_lot(
        env["spec"]["id"],
        wire_id,
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-BIG",
        planned_pieces=3333,
    )
    small = fixtures.open_production_lot(
        env["spec"]["id"],
        wire_id,
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-SMALL",
        planned_pieces=1000,
        press_window_start_at="2026-09-01T10:00:00Z",
        press_window_end_at="2026-09-01T14:00:00Z",
    )
    assert big["wire_reserved_kg"] == pytest.approx(big_reserved, abs=0.001), (
        f"Expected {big_reserved} reserved by the 3333-piece lot, "
        f"got {big['wire_reserved_kg']}"
    )
    assert small["wire_reserved_kg"] == pytest.approx(small_reserved, abs=0.001), (
        f"Expected {small_reserved} reserved by the 1000-piece lot, "
        f"got {small['wire_reserved_kg']}"
    )

    before = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert_wire_mass_ledger(before)
    assert before["reserved_mass_kg"] == pytest.approx(57.212, abs=0.001), (
        f"Expected both reservations summed to 57.212, "
        f"got {before['reserved_mass_kg']}"
    )
    assert before["available_mass_kg"] == pytest.approx(442.788, abs=0.001), (
        f"Expected available 442.788 with both lots in SETUP, "
        f"got {before['available_mass_kg']}"
    )

    validate_success(
        api.abort_heading(big["id"], {"reason": "PRESS_DOWN"}, engineer_headers)
    )

    after = validate_success(api.get_wire_lot(wire_id, engineer_headers))
    assert_wire_mass_ledger(after)
    assert after["reserved_mass_kg"] == pytest.approx(small_reserved, abs=0.001), (
        f"Only the surviving lot's {small_reserved} may remain reserved, "
        f"got {after['reserved_mass_kg']}"
    )
    assert after["available_mass_kg"] == pytest.approx(486.796, abs=0.001), (
        f"Expected available 486.796 after handing back 44.008, "
        f"got {after['available_mass_kg']}"
    )
    assert after["consumed_mass_kg"] == pytest.approx(0.0, abs=0.001), (
        f"Neither lot ran, so consumed stays 0.000, got {after['consumed_mass_kg']}"
    )

    surviving = validate_success(
        api.get_production_lot(small["id"], engineer_headers)
    )
    assert surviving["process_state"] == "SETUP", (
        f"The sibling lot is untouched by the abort, "
        f"got process_state {surviving['process_state']}"
    )
    assert surviving["wire_reserved_kg"] == pytest.approx(small_reserved, abs=0.001), (
        f"Expected the sibling to keep {small_reserved} reserved, "
        f"got {surviving['wire_reserved_kg']}"
    )


# ---------------------------------------------------------------------------
# The lot piece ledger, reversed by reopening a sealed pack
# ---------------------------------------------------------------------------


def test_pack_reopen_restores_the_lot_piece_ledger_to_its_pre_seal_state(
    api, engineer_headers, clerk_headers
):
    """Sealing moves 501 pieces into packed and reopening moves exactly those 501 back.

    PRD: "For every production lot, everything that came off the header is accounted for somewhere: `headed_count` plus `heading_scrap_count` equals `available_count` plus `scrap_count` plus `destructive_test_count` plus `packed_count`."

    PRD: "On success the pack moves `OPEN → SEALED`, `sealed_at` is stamped from the logical clock, the lot's `packed_count` grows by `declared_count` while its `available_count` shrinks by the same amount, the lot moves `CERTIFIED → PACKED`, and the pack's `version` and the lot's `version` each increment by 1."

    PRD: "The lot's `packed_count` shrinks by `declared_count` and its `available_count` grows by the same amount, leaving the conserved piece ledger of §2.8 exactly as it was before the seal."

    Design: Difficulty/compensating_invariant/lot_piece_ledger_restored_exactly_by_pack_reopen
    """
    env = fixtures.setup_certified_lot(
        spec_overrides={
            "packaging_mode": "BY_WEIGHT",
            "nominal_pack_count": 500,
            "pieces_per_kg": 62.5,
            "required_secondary_ops": ["THREAD_ROLL", "POINT"],
        },
        planned_pieces=10000,
        headed_count=9800,
        heading_scrap_count=150,
        ops=[
            {
                "op_type": "THREAD_ROLL",
                "sequence_no": 1,
                "pieces_out": 9750,
                "machine_code": "TR-1",
            },
            {
                "op_type": "POINT",
                "sequence_no": 2,
                "pieces_out": 9740,
                "machine_code": "PT-1",
            },
        ],
    )
    lot_id = env["lot"]["id"]

    before = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_production_lot(before)
    assert_lot_piece_ledger(before)
    assert (before["headed_count"], before["heading_scrap_count"]) == (9800, 150), (
        f"Expected 9800 headed and 150 heading scrap, got "
        f"{before['headed_count']} and {before['heading_scrap_count']}"
    )
    assert before["scrap_count"] == 210, (
        f"Expected scrap_count 210 (150 heading + 50 + 10 secondary), "
        f"got {before['scrap_count']}"
    )
    assert before["destructive_test_count"] == 99, (
        f"Expected 99 pieces consumed by the destructive test, "
        f"got {before['destructive_test_count']}"
    )
    assert before["available_count"] == 9641, (
        f"Expected available_count 9641 before the seal, "
        f"got {before['available_count']}"
    )
    assert before["packed_count"] == 0, (
        f"Nothing is packed yet, got packed_count {before['packed_count']}"
    )
    assert before["process_state"] == "CERTIFIED", (
        f"Expected process_state CERTIFIED before the seal, "
        f"got {before['process_state']}"
    )

    pack = validate_success(
        api.create_pack_unit(
            {
                "production_lot_id": lot_id,
                "certification_document_id": env["certificate"]["id"],
                "label_serial": "PK-0001",
                "net_weight_kg": 8.02,
                "label_fields_complete": True,
            },
            clerk_headers,
        ),
        201,
    )
    assert pack["declared_count"] == 501, (
        f"Expected 8.02 kg x 62.5 pieces/kg to declare 501 pieces, "
        f"got {pack['declared_count']}"
    )

    sealed = validate_success(api.seal_pack_unit(pack["id"], clerk_headers))
    assert sealed["status"] == "SEALED", (
        f"Expected status SEALED, got {sealed['status']}"
    )
    packed_lot = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(packed_lot)
    assert packed_lot["packed_count"] == 501, (
        f"Expected packed_count 501 after the seal, got {packed_lot['packed_count']}"
    )
    assert packed_lot["available_count"] == 9140, (
        f"Expected available_count 9140 after the seal, "
        f"got {packed_lot['available_count']}"
    )
    assert packed_lot["process_state"] == "PACKED", (
        f"Expected process_state PACKED after the seal, "
        f"got {packed_lot['process_state']}"
    )

    reopened = validate_success(
        api.reopen_pack_unit(
            pack["id"], {"reason": "MISCOUNT_SUSPECTED_AT_SCALE"}, clerk_headers
        )
    )
    assert reopened["status"] == "OPEN", (
        f"Expected status OPEN after the reopen, got {reopened['status']}"
    )
    assert reopened["declared_count"] == 501, (
        f"The reopen does not re-derive the label count, "
        f"got declared_count {reopened['declared_count']}"
    )

    after = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(after)
    assert after["packed_count"] == 0, (
        f"Expected packed_count 0 after the reopen, got {after['packed_count']}"
    )
    assert after["available_count"] == 9641, (
        f"Expected available_count back at 9641 after the reopen, "
        f"got {after['available_count']}"
    )
    assert after["scrap_count"] == 210, (
        f"The reopen touches neither scrap side, got scrap_count {after['scrap_count']}"
    )
    assert after["destructive_test_count"] == 99, (
        f"The reopen touches neither the destroyed sample, "
        f"got destructive_test_count {after['destructive_test_count']}"
    )
    assert after["process_state"] == "CERTIFIED", (
        f"Expected the lot rolled back to CERTIFIED, got {after['process_state']}"
    )
    assert after["disposition"] == "IN_PROCESS", (
        f"Expected disposition IN_PROCESS after the reopen, got {after['disposition']}"
    )


def test_pack_reopen_bumps_only_the_pack_and_the_lot_leaving_the_certificate_issued(
    api, engineer_headers, clerk_headers
):
    """The seal-then-reopen round trip costs the pack and the lot one version each and leaves the certificate alone.

    PRD: "Sealing a pack moves pieces from available into packed."

    PRD: "Reopening a sealed pack moves them back, exactly."

    PRD: "Both the pack's `version` and the lot's `version` increment by 1."

    Design: Difficulty/compensating_invariant/lot_piece_ledger_restored_exactly_by_pack_reopen
    """
    env = fixtures.setup_open_pack()
    lot_id = env["lot"]["id"]
    pack_id = env["pack"]["id"]
    cert_id = env["certificate"]["id"]

    lot_before = validate_success(api.get_production_lot(lot_id, engineer_headers))
    cert_before = validate_success(
        api.get_certification_document(cert_id, engineer_headers)
    )
    assert_lot_piece_ledger(lot_before)
    available_before = lot_before["available_count"]
    declared = env["pack"]["declared_count"]

    sealed = validate_success(api.seal_pack_unit(pack_id, clerk_headers))
    assert_versions_incremented(env["pack"], sealed)
    lot_sealed = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(lot_sealed)
    assert_versions_incremented(lot_before, lot_sealed)
    assert lot_sealed["packed_count"] == declared, (
        f"Expected packed_count {declared} after the seal, "
        f"got {lot_sealed['packed_count']}"
    )
    assert lot_sealed["available_count"] == available_before - declared, (
        f"Expected available_count {available_before - declared} after the seal, "
        f"got {lot_sealed['available_count']}"
    )

    reopened = validate_success(
        api.reopen_pack_unit(pack_id, {"reason": "RECOUNT"}, clerk_headers)
    )
    assert_versions_incremented(sealed, reopened)
    assert reopened["sealed_at"] is None, (
        f"Expected sealed_at cleared by the reopen, got {reopened['sealed_at']!r}"
    )

    lot_after = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(lot_after)
    assert_versions_incremented(lot_sealed, lot_after)
    assert lot_after["packed_count"] == 0, (
        f"Expected packed_count 0 after the reopen, got {lot_after['packed_count']}"
    )
    assert lot_after["available_count"] == available_before, (
        f"Expected available_count back at {available_before}, "
        f"got {lot_after['available_count']}"
    )

    cert_after = validate_success(
        api.get_certification_document(cert_id, engineer_headers)
    )
    assert cert_after["status"] == "ISSUED", (
        f"The reopen must not disturb the certificate, got status {cert_after['status']}"
    )
    assert cert_after["version"] == cert_before["version"], (
        f"Expected the certificate version unchanged at {cert_before['version']}, "
        f"got {cert_after['version']}"
    )


def test_pack_reopen_returns_only_its_own_pieces_while_a_sibling_stays_sealed(
    api, engineer_headers, clerk_headers
):
    """With two sealed packs, reopening one returns its 100 pieces and the lot stays PACKED.

    PRD: "The lot's `packed_count` shrinks by `declared_count` and its `available_count` grows by the same amount, leaving the conserved piece ledger of §2.8 exactly as it was before the seal."

    PRD: "The lot's `process_state` then moves `PACKED → CERTIFIED` only when no other pack unit of that lot remains in `status` `SEALED`, `SHIPPED` or `RECALLED`; otherwise the lot stays `PACKED`."

    Design: Difficulty/compensating_invariant/lot_piece_ledger_restored_exactly_by_pack_reopen
    """
    env = fixtures.setup_certified_lot()
    lot_id = env["lot"]["id"]
    cert_id = env["certificate"]["id"]

    before = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(before)
    available_before = before["available_count"]

    first = fixtures.open_pack(lot_id, cert_id, label_serial="PK-2026-0001")
    second = fixtures.open_pack(lot_id, cert_id, label_serial="PK-2026-0002")
    assert first["declared_count"] == 100 and second["declared_count"] == 100, (
        f"Expected two 100-piece packs, got {first['declared_count']} "
        f"and {second['declared_count']}"
    )

    validate_success(api.seal_pack_unit(first["id"], clerk_headers))
    validate_success(api.seal_pack_unit(second["id"], clerk_headers))

    both_sealed = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(both_sealed)
    assert both_sealed["packed_count"] == 200, (
        f"Expected packed_count 200 with both packs sealed, "
        f"got {both_sealed['packed_count']}"
    )
    assert both_sealed["available_count"] == available_before - 200, (
        f"Expected available_count {available_before - 200}, "
        f"got {both_sealed['available_count']}"
    )

    validate_success(
        api.reopen_pack_unit(first["id"], {"reason": "RECOUNT"}, clerk_headers)
    )

    after = validate_success(api.get_production_lot(lot_id, engineer_headers))
    assert_lot_piece_ledger(after)
    assert after["packed_count"] == 100, (
        f"Only the reopened pack's 100 pieces come back, so packed_count must be "
        f"100, got {after['packed_count']}"
    )
    assert after["available_count"] == available_before - 100, (
        f"Expected available_count {available_before - 100} with one pack still "
        f"sealed, got {after['available_count']}"
    )
    assert after["process_state"] == "PACKED", (
        f"A pack of the lot is still SEALED, so the lot stays PACKED, "
        f"got {after['process_state']}"
    )

    still_sealed = validate_success(api.get_pack_unit(second["id"], engineer_headers))
    assert still_sealed["status"] == "SEALED", (
        f"The sibling pack is untouched, got status {still_sealed['status']}"
    )
