"""Where fastener records begin life and how they take their first legal step.

This module covers the opening states the PRD declares for incoming material,
tooling, furnaces and every workflow child; the wire lot's release to the heading
floor; the secondary-operations stage closing itself when the last required
operation is closed; the destructive test's consumption of sample pieces out of
the lot's piece ledger; and the two calls the plant refuses because the lot has
either already moved past the transition (a replayed heading report) or has not
yet moved far enough to make it (queueing a secondary operation from setup).
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiErrorId,
    assert_furnace,
    assert_heading_tool,
    assert_heat_treat_run,
    assert_lot_piece_ledger,
    assert_production_lot,
    assert_secondary_operation,
    assert_steel_heat,
    assert_wire_lot,
    assert_wire_mass_ledger,
    factories,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

# The unplated reference part of the PRD's own arithmetic: plating_spec NONE (so
# no relief bake and the lot may be tested straight from HEAT_TREATED), a
# decarburization ceiling of 0.100 mm and 62.5 pieces per kilogram.
CHAIN_B_SPEC: Dict[str, Any] = {
    "max_decarb_depth_mm": 0.100,
    "pieces_per_kg": 62.5,
}


def _is_empty(value: Any) -> bool:
    """The PRD's "empty" for a field the server has not written yet."""
    return value is None or value == ""


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------
def test_material_tooling_and_furnace_records_open_in_their_declared_states(
    api, engineer_headers, inspector_headers
):
    """A fresh heat, wire lot, die set and furnace each open on their own declared state.

    PRD: "A new heat begins with `cert_status` of `PENDING`, with `lab_report_reference`, `verified_at`, `verified_by_user_id` and `counterfeit_reason` all empty."

    PRD: "The three mass ledger members are initialised so the identity holds trivially — `available_mass_kg` equals `gross_mass_kg`, while `reserved_mass_kg` and `consumed_mass_kg` are both zero — and `status` starts at `DRAWN` with `quarantine_source` of `NONE` and `inspected_at` empty."

    PRD: "A fresh set begins `AVAILABLE`, with `regrind_count` and `cumulative_pieces_current_cycle` at zero, an empty `cycle_pieces_history`, `completed_cycle_count` and `lifetime_pieces` at zero, `observed_avg_cycle_pieces` empty, and `mounted_press_code` and `condemn_reason` both empty."

    PRD: "A furnace starts `IDLE` with `last_run_end_at` empty."

    PRD: "**`version`** (integer): starts at 1 when the record is created and increments by exactly 1 on every mutation of that record."

    Design: Corner/state_machines/root_entities_start_in_their_declared_initial_states
    """
    fixtures.set_clock("2026-09-01T06:00:00Z")

    heat = validate_success(
        api.create_steel_heat(factories.create_steel_heat_payload(), inspector_headers),
        201,
    )
    wire = validate_success(
        api.create_wire_lot(
            factories.create_wire_lot_payload(heat["id"]), engineer_headers
        ),
        201,
    )
    tool = validate_success(
        api.create_heading_tool(
            factories.create_heading_tool_payload(), engineer_headers
        ),
        201,
    )
    furnace = validate_success(
        api.create_furnace(factories.create_furnace_payload(), engineer_headers), 201
    )

    assert_steel_heat(heat)
    assert_wire_lot(wire)
    assert_heading_tool(tool)
    assert_furnace(furnace)

    # The steel heat is unadjudicated paperwork.
    assert heat["cert_status"] == "PENDING", (
        f"Expected a new heat at PENDING, got {heat['cert_status']}"
    )
    for field in (
        "lab_report_reference",
        "verified_at",
        "verified_by_user_id",
        "counterfeit_reason",
    ):
        assert _is_empty(heat.get(field)), (
            f"Expected {field} empty on a PENDING heat, got {heat.get(field)!r}"
        )

    # The wire lot is merely drawn: no inspector has released it.
    assert wire["status"] == "DRAWN", (
        f"Expected a new wire lot at DRAWN, got {wire['status']}"
    )
    assert wire["quarantine_source"] == "NONE", (
        f"Expected quarantine_source NONE on a fresh wire lot, got {wire['quarantine_source']}"
    )
    assert _is_empty(wire.get("inspected_at")), (
        f"Expected inspected_at empty before release, got {wire.get('inspected_at')!r}"
    )
    assert wire["available_mass_kg"] == pytest.approx(500.0, abs=0.001), (
        f"Expected available_mass_kg to equal gross 500.000, got {wire['available_mass_kg']}"
    )
    assert wire["reserved_mass_kg"] == pytest.approx(0.0, abs=0.001)
    assert wire["consumed_mass_kg"] == pytest.approx(0.0, abs=0.001)

    # The die set is on the shelf, not on a press.
    assert tool["status"] == "AVAILABLE", (
        f"Expected a new die set at AVAILABLE, got {tool['status']}"
    )
    assert tool["regrind_count"] == 0, "A fresh set has no regrinds behind it"
    assert tool["cumulative_pieces_current_cycle"] == 0, "No pieces headed yet"
    assert tool["cycle_pieces_history"] == [], "No cycle has closed yet"
    assert tool["completed_cycle_count"] == 0, "No cycle has closed yet"
    assert tool["lifetime_pieces"] == 0, "No pieces headed yet"
    assert _is_empty(tool.get("observed_avg_cycle_pieces")), (
        f"Expected observed_avg_cycle_pieces empty with no history, "
        f"got {tool.get('observed_avg_cycle_pieces')!r}"
    )
    for field in ("mounted_press_code", "condemn_reason"):
        assert _is_empty(tool.get(field)), (
            f"Expected {field} empty on an AVAILABLE set, got {tool.get(field)!r}"
        )

    # The furnace is cold and free.
    assert furnace["status"] == "IDLE", (
        f"Expected a new furnace at IDLE, got {furnace['status']}"
    )
    assert _is_empty(furnace.get("last_run_end_at")), (
        f"Expected last_run_end_at empty on a new furnace, got {furnace.get('last_run_end_at')!r}"
    )

    for label, row in (
        ("steel heat", heat),
        ("wire lot", wire),
        ("die set", tool),
        ("furnace", furnace),
    ):
        assert row["version"] == 1, (
            f"Expected version 1 on a freshly created {label}, got {row['version']}"
        )


def test_workflow_children_are_born_unexecuted(
    api, engineer_headers, heat_treat_headers, inspector_headers
):
    """A queued operation, a booked run, an opened test and a fresh draft all start un-run.

    PRD: "The new operation is created in `status` `PENDING` with `pieces_in` taken from the lot's current `available_count` — the client never supplies it — and with `performed_after_heat_treat` capturing whether the lot's `heat_treat_completed` flag was already true at the moment of creation."

    PRD: "Its `pieces_out` and `scrap_pieces` stay empty while the operation is `PENDING`."

    PRD: "A booked run begins in `status` `PLANNED` with `started_at`, `completed_at`, `core_hardness_hv`, `surface_decarb_depth_mm`, `total_decarb_depth_mm` all empty and `result` of `PENDING`; booking does not occupy the furnace."

    PRD: "A new test starts with `result` `PENDING`, with `proof_load_failures`, `tensile_failures`, `min_measured_core_hardness_hv`, `total_failures` and `completed_at` all empty."

    PRD: "A fresh draft starts in `status` `DRAFT` with `revision` of 1 and `signed_by_user_id`, `issued_at` and `revoked_reason` all empty."

    Design: Corner/state_machines/child_entities_start_pending_planned_and_draft
    """
    env = fixtures.setup_headed_lot(unplated=True, spec_overrides=dict(CHAIN_B_SPEC))
    lot_id = env["lot"]["id"]

    # --- the secondary operation is queued, not performed -------------------
    op = validate_success(
        api.queue_secondary_operation(
            lot_id, factories.queue_secondary_operation_payload(), engineer_headers
        ),
        201,
    )
    assert_secondary_operation(op)
    assert op["status"] == "PENDING", (
        f"Expected a queued operation at PENDING, got {op['status']}"
    )
    assert op["pieces_in"] == 4900, (
        f"Expected pieces_in to take the lot's available_count 4900, got {op['pieces_in']}"
    )
    for field in ("pieces_out", "scrap_pieces"):
        assert _is_empty(op.get(field)), (
            f"Expected {field} empty while the operation is PENDING, got {op.get(field)!r}"
        )
    assert op["performed_after_heat_treat"] is False, (
        "The lot's heat_treat_completed was still false when the operation was created"
    )
    fixtures.complete_op(op["id"], 4850)

    # --- the heat treatment run is booked, not started ---------------------
    run = validate_success(
        api.create_heat_treat_run(
            factories.create_heat_treat_run_payload(lot_id, env["furnace"]["id"]),
            heat_treat_headers,
        ),
        201,
    )
    assert_heat_treat_run(run)
    assert run["status"] == "PLANNED", (
        f"Expected a booked run at PLANNED, got {run['status']}"
    )
    for field in (
        "started_at",
        "completed_at",
        "core_hardness_hv",
        "surface_decarb_depth_mm",
        "total_decarb_depth_mm",
    ):
        assert _is_empty(run.get(field)), (
            f"Expected {field} empty on a PLANNED run, got {run.get(field)!r}"
        )
    assert run["result"] == "PENDING", (
        f"Expected result PENDING on a PLANNED run, got {run['result']}"
    )
    assert run["charge_mass_kg"] == pytest.approx(97.000, abs=0.001), (
        f"Expected a derived charge of 97.000 kg for 4850 blanks of 20.0 g, "
        f"got {run['charge_mass_kg']}"
    )
    booked_furnace = fixtures.read_furnace(env["furnace"]["id"])
    assert booked_furnace["status"] == "IDLE", (
        "Booking does not occupy the furnace, so it must still read IDLE"
    )

    fixtures.start_heat_treat(run["id"], at="2026-09-01T19:00:00Z")
    fixtures.record_heat_treat_results(
        run["id"],
        at="2026-09-01T22:00:00Z",
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.020,
    )

    # --- the lot test is opened, not adjudicated --------------------------
    test = validate_success(
        api.create_lot_test(factories.create_lot_test_payload(lot_id), inspector_headers),
        201,
    )
    assert test["result"] == "PENDING", (
        f"Expected a newly opened test at PENDING, got {test['result']}"
    )
    for field in (
        "proof_load_failures",
        "tensile_failures",
        "min_measured_core_hardness_hv",
        "total_failures",
        "completed_at",
    ):
        assert _is_empty(test.get(field)), (
            f"Expected {field} empty on a PENDING test, got {test.get(field)!r}"
        )
    assert test["sample_size"] == 70, (
        f"Expected a normal-inspection sample of 70 for 4850 available pieces, "
        f"got {test['sample_size']}"
    )
    assert test["acceptance_number"] == 1, (
        f"Expected acceptance_number 1 for a sample of 70, got {test['acceptance_number']}"
    )
    assert test["severity"] == "NORMAL", (
        f"Expected NORMAL severity on an unremarkable lot, got {test['severity']}"
    )
    tested_lot = fixtures.read_lot(lot_id)
    assert tested_lot["inspection_severity"] == "NORMAL", (
        f"The chosen severity freezes onto the lot, got {tested_lot['inspection_severity']}"
    )

    fixtures.record_lot_test_results(
        test["id"],
        proof_load_failures=0,
        tensile_failures=0,
        min_measured_core_hardness_hv=322.0,
    )

    # --- the certificate is drafted, not signed ---------------------------
    cert = validate_success(
        api.create_certification_document(
            factories.create_certification_document_payload(
                lot_id,
                test["id"],
                fixtures.lot_version(lot_id),
                cert_serial="CERT-0001",
            ),
            inspector_headers,
        ),
        201,
    )
    assert cert["status"] == "DRAFT", (
        f"Expected a fresh draft at DRAFT, got {cert['status']}"
    )
    assert cert["revision"] == 1, (
        f"Expected revision 1 on a fresh draft, got {cert['revision']}"
    )
    assert cert["cert_serial"] == "CERT-0001", (
        f"Expected the printed serial CERT-0001, got {cert['cert_serial']}"
    )
    for field in ("signed_by_user_id", "issued_at", "revoked_reason"):
        assert _is_empty(cert.get(field)), (
            f"Expected {field} empty on a DRAFT certificate, got {cert.get(field)!r}"
        )


# ---------------------------------------------------------------------------
# The first legal move out of DRAWN
# ---------------------------------------------------------------------------
def test_wire_lot_release_stamps_inspected_at_and_bumps_version(api, inspector_headers):
    """Releasing drawn wire stamps the clock and bumps the version, touching no mass.

    PRD: "On success the lot moves `DRAWN → RELEASED`, `inspected_at` is stamped from the logical clock, and the lot's `version` increments by 1."

    PRD: "The three mass ledger members are initialised so the identity holds trivially — `available_mass_kg` equals `gross_mass_kg`, while `reserved_mass_kg` and `consumed_mass_kg` are both zero — and `status` starts at `DRAWN` with `quarantine_source` of `NONE` and `inspected_at` empty."

    Design: Corner/state_machines/wire_lot_release_stamps_inspected_at_and_bumps_version
    """
    fixtures.set_clock("2026-09-01T06:00:00Z")
    heat = fixtures.create_verified_heat()
    wire = fixtures.register_wire_lot(heat["id"])
    assert wire["status"] == "DRAWN", "Precondition: the lot is merely drawn"
    heat_before = fixtures.read_heat(heat["id"])

    # The release happens twelve hours after the coil was recorded.
    fixtures.set_clock("2026-09-01T18:00:00Z")
    released = validate_success(api.release_wire_lot(wire["id"], inspector_headers), 200)

    assert_wire_lot(released)
    assert released["status"] == "RELEASED", (
        f"Expected RELEASED after a clean release, got {released['status']}"
    )
    assert is_iso8601_timestamp(released["inspected_at"]), (
        f"inspected_at must be an ISO 8601 stamp, got {released['inspected_at']!r}"
    )
    assert released["inspected_at"].startswith("2026-09-01T18:00:00"), (
        f"inspected_at must read the logical clock at release (18:00:00Z), "
        f"got {released['inspected_at']}"
    )
    assert released["version"] == wire["version"] + 1, (
        f"Expected version {wire['version'] + 1} after the release, got {released['version']}"
    )

    # Release moves no mass: reservations only happen when a lot is opened.
    assert released["available_mass_kg"] == pytest.approx(500.000, abs=0.001), (
        f"Expected available_mass_kg still 500.000 after release, "
        f"got {released['available_mass_kg']}"
    )
    assert released["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"Expected reserved_mass_kg still 0.000 after release, "
        f"got {released['reserved_mass_kg']}"
    )
    assert released["consumed_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"Expected consumed_mass_kg still 0.000 after release, "
        f"got {released['consumed_mass_kg']}"
    )
    assert_wire_mass_ledger(released)

    heat_after = fixtures.read_heat(heat["id"])
    assert heat_after["version"] == heat_before["version"], (
        f"The release mutates only the wire lot, but the heat's version moved from "
        f"{heat_before['version']} to {heat_after['version']}"
    )


# ---------------------------------------------------------------------------
# The stage that closes itself
# ---------------------------------------------------------------------------
def test_closing_the_last_required_operation_bubbles_the_lot_to_secondary_done(
    api, engineer_headers
):
    """The only required operation moving to DONE flips the lot to SECONDARY_DONE at once.

    PRD: "On success the operation moves `PENDING → DONE` (a terminal status), `pieces_out` is recorded, and `scrap_pieces` is set to `pieces_in` minus `pieces_out`."

    PRD: "The lot absorbs the yield: its `available_count` is replaced by `pieces_out` and its `scrap_count` grows by `scrap_pieces`, keeping the piece ledger of §2.8 balanced."

    PRD: "When the lot has no operation left in `status` `PENDING` *and* the operations due at this stage are all `DONE`, the lot moves `SECONDARY_IN_PROGRESS → SECONDARY_DONE`."

    PRD: "For a part with `thread_timing` of `BEFORE_HEAT_TREAT`, every `op_type` listed in `required_secondary_ops` must have a `DONE` operation."

    Design: Corner/state_machines/secondary_stage_bubbles_up_to_done_when_last_required_op_completes
    """
    env = fixtures.setup_headed_lot(unplated=True, spec_overrides=dict(CHAIN_B_SPEC))
    lot_id = env["lot"]["id"]

    op = fixtures.queue_op(lot_id, op_type="THREAD_ROLL", sequence_no=1, machine_code="TR-1")
    lot_before = fixtures.read_lot(lot_id)
    assert lot_before["process_state"] == "SECONDARY_IN_PROGRESS", (
        f"Precondition: queueing moved the lot into secondary operations, "
        f"got {lot_before['process_state']}"
    )
    assert op["pieces_in"] == 4900, f"Precondition: pieces_in 4900, got {op['pieces_in']}"

    done = validate_success(
        api.complete_secondary_operation(op["id"], {"pieces_out": 4850}, engineer_headers),
        200,
    )

    assert_secondary_operation(done)
    assert done["status"] == "DONE", f"Expected DONE after closing, got {done['status']}"
    assert done["pieces_out"] == 4850, (
        f"Expected pieces_out 4850, got {done['pieces_out']}"
    )
    assert done["scrap_pieces"] == 50, (
        f"Expected scrap_pieces 4900 - 4850 = 50, got {done['scrap_pieces']}"
    )

    lot_after = fixtures.read_lot(lot_id)
    assert_production_lot(lot_after)
    assert lot_after["process_state"] == "SECONDARY_DONE", (
        f"The lot's only required operation is DONE, so it must have bubbled up to "
        f"SECONDARY_DONE in the same request; got {lot_after['process_state']}"
    )
    assert lot_after["available_count"] == 4850, (
        f"available_count is replaced by pieces_out 4850, got {lot_after['available_count']}"
    )
    assert lot_after["scrap_count"] == 110, (
        f"scrap_count grows by 50 from 60 to 110, got {lot_after['scrap_count']}"
    )
    assert lot_after["headed_count"] == 4900, "Heading output is untouched by the yield"
    assert lot_after["heading_scrap_count"] == 60, (
        "Heading scrap is untouched by the yield"
    )
    assert_lot_piece_ledger(lot_after)
    assert lot_after["disposition"] == "IN_PROCESS", (
        f"Closing an operation frees no hold, got {lot_after['disposition']}"
    )
    assert lot_after["version"] > lot_before["version"], (
        f"The lot was mutated, so its version must have advanced past "
        f"{lot_before['version']}, got {lot_after['version']}"
    )


# ---------------------------------------------------------------------------
# The destructive test consumes its sample
# ---------------------------------------------------------------------------
def test_opening_a_lot_test_moves_sample_pieces_into_destructive_consumption(
    api, inspector_headers
):
    """Opening the test moves exactly sample_size pieces out of available inventory.

    PRD: "The test's `destructive` flag defaults to true and the create payload offers no way to change it, so the sample is consumed: when `destructive` is true, the lot's `destructive_test_count` grows by `sample_size` and its `available_count` shrinks by the same amount, keeping the piece ledger balanced."

    PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

    PRD: "The lot moves into `TESTING`: from `BAKED → TESTING` in the ordinary case, from `HEAT_TREATED → TESTING` or `SECONDARY_DONE → TESTING` for an unplated part (both of which also compute `risk_score_pre_test` at this moment, with the bake term taken as zero), and `TESTING → TESTING` as a self-loop on a retest."

    PRD: "The score is 0.30 multiplied by the heat term, plus 0.20 multiplied by the tool term, plus 0.25 multiplied by the bake term, plus 0.25 multiplied by the decarburization term, with the sum rounded half up to two decimal places exactly once at the end — the individual weighted terms are never rounded on their own."

    Design: Corner/state_machines/lot_test_creation_syncs_the_piece_ledger
    """
    env = fixtures.setup_heat_treated_lot(
        unplated=True, spec_overrides=dict(CHAIN_B_SPEC)
    )
    lot_id = env["lot"]["id"]

    lot_before = fixtures.read_lot(lot_id)
    assert lot_before["process_state"] == "HEAT_TREATED", (
        f"Precondition: an unplated part is tested from HEAT_TREATED, "
        f"got {lot_before['process_state']}"
    )
    assert lot_before["available_count"] == 4850, (
        f"Precondition: 4850 available pieces, got {lot_before['available_count']}"
    )
    assert lot_before["destructive_test_count"] == 0, (
        "Precondition: nothing destroyed yet"
    )

    test = validate_success(
        api.create_lot_test(factories.create_lot_test_payload(lot_id), inspector_headers),
        201,
    )

    assert test["destructive"] is True, (
        "destructive defaults to true and the payload offers no way to change it"
    )
    assert test["sample_size"] == 70, (
        f"Expected max(8, ceil(sqrt(4850))) = 70 sample pieces, got {test['sample_size']}"
    )

    lot_after = fixtures.read_lot(lot_id)
    assert_production_lot(lot_after)
    assert lot_after["available_count"] == 4780, (
        f"Expected available_count 4850 - 70 = 4780, got {lot_after['available_count']}"
    )
    assert lot_after["destructive_test_count"] == 70, (
        f"Expected destructive_test_count 0 + 70 = 70, got "
        f"{lot_after['destructive_test_count']}"
    )
    assert lot_after["scrap_count"] == 110, (
        f"Sampling moves nothing into scrap, expected 110, got {lot_after['scrap_count']}"
    )
    assert lot_after["packed_count"] == 0, (
        f"Sampling packs nothing, expected 0, got {lot_after['packed_count']}"
    )
    assert_lot_piece_ledger(lot_after)
    assert lot_after["process_state"] == "TESTING", (
        f"Expected the lot to move into TESTING, got {lot_after['process_state']}"
    )
    assert lot_after["risk_score_pre_test"] == pytest.approx(5.83, abs=0.001), (
        f"Expected the pre-test score 5.83 computed at test opening with a zero bake "
        f"term, got {lot_after['risk_score_pre_test']}"
    )


# ---------------------------------------------------------------------------
# Calls the machine refuses
# ---------------------------------------------------------------------------
def test_second_complete_heading_call_is_refused_and_charges_nothing_twice(
    api, engineer_headers
):
    """Replaying the heading report is refused and neither the die set nor the wire moves.

    PRD: "The lot must be in `process_state` `SETUP` with `disposition` `IN_PROCESS` — a lot on hold reports `ERR_LOT_ON_HOLD` and a quarantined lot reports `ERR_LOT_QUARANTINED` — and its die set must still be `MOUNTED`, or the report is refused with `ERR_INVALID_TOOL_STATE`."

    PRD: "The wire ledger settles: the actually consumed mass is the sum of the two reported counts multiplied by `blank_mass_g`, divided by 1000, rounded half up to three decimal places; the lot's original `wire_reserved_kg` is subtracted from the wire lot's `reserved_mass_kg`, the consumed mass is added to `consumed_mass_kg`, and the difference between the reservation and the consumption is added back to `available_mass_kg` — which will be negative when the lot over-consumed."

    PRD: "The first cascade link advances the die set: `cumulative_pieces_current_cycle` grows by the sum of the two reported counts and `lifetime_pieces` is recomputed."

    Design: Corner/state_machines/repeated_complete_heading_is_rejected_on_the_second_call
    """
    env = fixtures.setup_headed_lot(unplated=True, spec_overrides=dict(CHAIN_B_SPEC))
    lot_id = env["lot"]["id"]
    headed_version = env["lot"]["version"]
    assert env["lot"]["process_state"] == "HEADED", (
        f"Precondition: the first report landed, got {env['lot']['process_state']}"
    )

    resp = api.complete_heading(
        lot_id,
        factories.complete_heading_payload(headed_count=4900, heading_scrap_count=60),
        engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE.value)

    lot = fixtures.read_lot(lot_id)
    assert lot["process_state"] == "HEADED", (
        f"The refused replay leaves the lot at HEADED, got {lot['process_state']}"
    )
    assert lot["headed_count"] == 4900, (
        f"Expected headed_count still 4900, got {lot['headed_count']}"
    )
    assert lot["available_count"] == 4900, (
        f"Expected available_count still 4900, got {lot['available_count']}"
    )
    assert lot["version"] == headed_version, (
        f"A refused request mutates nothing, so the lot's version must still be "
        f"{headed_version}, got {lot['version']}"
    )
    assert_lot_piece_ledger(lot)

    tool = fixtures.read_tool(env["tool"]["id"])
    assert tool["cumulative_pieces_current_cycle"] == 4960, (
        f"The die set must be charged once for 4900 + 60 pieces, not twice; "
        f"got {tool['cumulative_pieces_current_cycle']}"
    )
    assert tool["lifetime_pieces"] == 4960, (
        f"Expected lifetime_pieces 4960, got {tool['lifetime_pieces']}"
    )

    wire = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire["consumed_mass_kg"] == pytest.approx(99.200, abs=0.001), (
        f"Expected consumed_mass_kg settled once at 99.200, got {wire['consumed_mass_kg']}"
    )
    assert wire["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"Expected reserved_mass_kg 0.000 after the single settlement, "
        f"got {wire['reserved_mass_kg']}"
    )
    assert wire["available_mass_kg"] == pytest.approx(400.800, abs=0.001), (
        f"Expected available_mass_kg 400.800 after the single settlement, "
        f"got {wire['available_mass_kg']}"
    )
    assert_wire_mass_ledger(wire)


def test_secondary_operation_cannot_be_queued_from_setup(api, engineer_headers):
    """A lot still in setup has no headed pieces to route, so queueing is refused.

    PRD: "Queueing requires the lot's `disposition` to be `IN_PROCESS` and its `process_state` to be `HEADED`, `HEAT_TREATED` or `SECONDARY_IN_PROGRESS`; anything else is refused with `ERR_INVALID_LOT_STATE`."

    Design: Corner/state_machines/secondary_operation_cannot_be_queued_from_setup
    """
    env = fixtures.setup_lot_in_setup(unplated=True, spec_overrides=dict(CHAIN_B_SPEC))
    lot_id = env["lot"]["id"]
    assert env["lot"]["process_state"] == "SETUP", (
        f"Precondition: the lot is still in setup, got {env['lot']['process_state']}"
    )
    assert env["lot"]["disposition"] == "IN_PROCESS", (
        f"Precondition: the lot is not frozen, got {env['lot']['disposition']}"
    )
    lot_version_before = env["lot"]["version"]

    resp = api.queue_secondary_operation(
        lot_id, factories.queue_secondary_operation_payload(), engineer_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE.value)

    items, pagination = validate_paginated(
        api.list_secondary_operations(lot_id, engineer_headers)
    )
    assert items == [], f"The refused call must write no operation row, got {items}"
    assert pagination["total_count"] == 0, (
        f"Expected total_count 0 secondary operations, got {pagination['total_count']}"
    )

    lot = fixtures.read_lot(lot_id)
    assert lot["process_state"] == "SETUP", (
        f"The refused call leaves the lot in SETUP, got {lot['process_state']}"
    )
    assert lot["version"] == lot_version_before, (
        f"A refused request mutates nothing, so the lot's version must still be "
        f"{lot_version_before}, got {lot['version']}"
    )
