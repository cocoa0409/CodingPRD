"""BatteryPack assembly axis (§3.3–§3.6): pack creation, welding records and
certification, BMS flashing, UN38.3 dossiers, plus the logistics pick."""

from decimal import Decimal

from flask import Blueprint, request

import db
from domain import (
    new_row, touch, sorted_rows, get_program, get_pack, get_weld_record,
    get_dossier, require_program_open, raise_if_pack_under_recall,
    ser_pack, ser_weld_record, ser_flash_record, ser_dossier,
    compute_heat_dose, soc_band_plain, compute_un_score, mint_serial_number,
    check_lot_depletion, active_placement_for_pack, release_placement,
    decrement_risk, WELD_PROFILES, WELD_CEILING, UN_PASS_THRESHOLD,
    NON_TERMINAL_DOSSIER_STATES,
)
from errors import (
    err_bom_not_found, err_firmware_not_found, err_cross_program,
    err_stale_version, err_invalid_request, err_pack_not_built,
    err_pack_not_weld_recorded, err_weld_already_certified, err_sod_weld_certify,
    err_weld_profile_mismatch, err_heat_dose_exceeded, err_pack_not_weld_certified,
    err_firmware_not_approved, err_pack_not_bms_flashed, err_dossier_already_open,
    err_dossier_not_open, err_incomplete_test_matrix, err_dossier_not_tests_recorded,
    err_pack_not_test_queued, err_dossier_not_submitted, err_dossier_not_pass,
    err_pack_not_classified, err_pack_not_stored,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import (
    get_body, req_field, as_str, as_int, as_decimal, as_bool, as_enum,
    round_half_up,
)

bp = Blueprint("battery_packs", __name__)

DOSSIER_TEST_FIELDS = (
    "altitude_sim_kpa",
    "thermal_cycles",
    "vibration_minutes",
    "shock_g_peak",
    "external_short_circuit_ok",
    "impact_crush_ok",
    "overcharge_ok",
    "forced_discharge_ok",
)


def _packs_of(program_id):
    return sorted_rows([r for r in db.packs.values() if r["program_id"] == program_id])


# ---------------------------------------------------------------------------
# BatteryPack
# ---------------------------------------------------------------------------

@bp.route("/integration-programs/<programId>/battery-packs", methods=["POST"])
@require_roles("AssemblyLead")
def create_pack(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    bom_id = as_str(req_field(body, "bom_id"), "bom_id")
    expected_bom_version = as_int(
        req_field(body, "expected_bom_version"), "expected_bom_version"
    )

    bom = db.boms.get(bom_id)
    if bom is None:
        raise err_bom_not_found()
    require_program_open(program)
    # priority 12: cross-program referential integrity
    if bom["program_id"] != program["id"]:
        raise err_cross_program()
    # priority 22: OCC on PackBOM.version (§2.10)
    if bom["version"] != expected_bom_version:
        raise err_stale_version()

    lot = db.cell_lots[bom["cell_lot_id"]]
    soc = lot["measured_soc_percent"]

    row = new_row()
    row.update(
        program_id=program["id"],
        serial_number=mint_serial_number(program),
        bom_id=bom["id"],
        cell_lot_id=bom["cell_lot_id"],
        pack_energy_wh=bom["nominal_energy_wh"],
        assembly_status="BUILT",
        logistics_status="NOT_STORED",
        soc_percent=soc,
        soc_band=soc_band_plain(soc),
        shipping_classification="NONE",
        welding_heat_dose_j=None,
        bms_firmware_id=None,
        dossier_id=None,
        storage_location_id=None,
        active_recall_id=None,
        is_safe_discharged=False,
        disposition="IN_SERVICE",
    )
    db.packs[row["id"]] = row

    # consuming the BOM locks it (welding_profile / cells_required immutable)
    bom["is_locked"] = True
    touch(bom)
    # automatic lot depletion once locked commitment reaches cell_count
    check_lot_depletion(lot)
    return success_created(ser_pack(row))


@bp.route("/integration-programs/<programId>/battery-packs", methods=["GET"])
@require_roles()
def list_packs(actor, programId):
    get_program(programId)
    rows = [r for r in db.packs.values() if r["program_id"] == programId]
    for f in ("bom_id", "cell_lot_id", "storage_location_id", "active_recall_id"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r.get(f) == v]
    return success_list(sorted_rows(rows), ser_pack)


@bp.route("/integration-programs/<programId>/battery-packs/<packId>", methods=["GET"])
@require_roles()
def get_one_pack(actor, programId, packId):
    get_program(programId)
    return success_object(ser_pack(get_pack(programId, packId)))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/pick", methods=["POST"])
@require_roles("LogisticsCoordinator")
def pick_pack(actor, programId, packId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    get_body()
    require_program_open(program)
    if pack["logistics_status"] != "STORED":
        raise err_pack_not_stored()
    # priority 20: recall capture blocks pick
    raise_if_pack_under_recall(pack)

    placement = active_placement_for_pack(pack["id"])
    if placement is not None:
        release_placement(placement, pack)
    pack["logistics_status"] = "PICKED"
    touch(pack)
    return success_object(ser_pack(pack))


# ---------------------------------------------------------------------------
# WeldingParameterRecord (§3.4)
# ---------------------------------------------------------------------------

@bp.route("/integration-programs/<programId>/battery-packs/<packId>/welding-records", methods=["POST"])
@require_roles("AssemblyLead")
def record_weld(actor, programId, packId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    body = get_body(required=True)
    weld_count = as_int(req_field(body, "weld_count"), "weld_count")
    if weld_count < 1:
        raise err_invalid_request("weld_count must be >= 1")
    current_amps = round_half_up(
        as_decimal(req_field(body, "current_amps"), "current_amps"), 1
    )
    pulse_ms = as_int(req_field(body, "pulse_ms"), "pulse_ms")
    if pulse_ms < 1:
        raise err_invalid_request("pulse_ms must be >= 1")
    electrode_force_n = round_half_up(
        as_decimal(req_field(body, "electrode_force_n"), "electrode_force_n"), 1
    )
    weld_profile_used = as_enum(
        req_field(body, "weld_profile_used"), "weld_profile_used", WELD_PROFILES
    )

    require_program_open(program)
    if pack["assembly_status"] != "BUILT":
        raise err_pack_not_built()

    heat = compute_heat_dose(
        weld_count, current_amps, pulse_ms, electrode_force_n, weld_profile_used
    )
    rec = new_row(common=False)
    rec.update(
        battery_pack_id=pack["id"],
        program_id=program["id"],
        operator_id=actor.user_id,
        certified_by_id=None,
        weld_count=weld_count,
        current_amps=current_amps,
        pulse_ms=pulse_ms,
        electrode_force_n=electrode_force_n,
        weld_profile_used=weld_profile_used,
        heat_dose_j=heat,
        is_certified=False,
    )
    db.weld_records[rec["id"]] = rec

    pack["welding_heat_dose_j"] = heat
    pack["assembly_status"] = "WELD_RECORDED"
    touch(pack)
    return success_created(ser_weld_record(rec))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/welding-records", methods=["GET"])
@require_roles()
def list_weld_records(actor, programId, packId):
    get_program(programId)
    pack = get_pack(programId, packId)
    rows = sorted_rows(
        [r for r in db.weld_records.values() if r["battery_pack_id"] == pack["id"]]
    )
    return success_list(rows, ser_weld_record)


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/welding-records/<recordId>", methods=["GET"])
@require_roles()
def get_one_weld_record(actor, programId, packId, recordId):
    get_program(programId)
    pack = get_pack(programId, packId)
    rec = get_weld_record(programId, pack["id"], recordId)
    return success_object(ser_weld_record(rec))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/welding-records/<recordId>/certify", methods=["POST"])
@require_roles("QualityEngineer")
def certify_weld(actor, programId, packId, recordId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    rec = get_weld_record(programId, pack["id"], recordId)
    get_body()
    require_program_open(program)
    if pack["assembly_status"] != "WELD_RECORDED":
        raise err_pack_not_weld_recorded()
    if rec["is_certified"]:
        raise err_weld_already_certified()
    # priority 6: segregation of duties — certifier != weld operator
    if actor.user_id == rec["operator_id"]:
        raise err_sod_weld_certify()
    # priority 9: profile match, then heat-dose ceiling
    bom = db.boms[pack["bom_id"]]
    if rec["weld_profile_used"] != bom["welding_profile"]:
        raise err_weld_profile_mismatch()
    if rec["heat_dose_j"] > WELD_CEILING[bom["welding_profile"]]:
        raise err_heat_dose_exceeded()

    rec["is_certified"] = True
    rec["certified_by_id"] = actor.user_id
    pack["assembly_status"] = "WELD_CERTIFIED"
    touch(pack)
    return success_object(ser_weld_record(rec))


# ---------------------------------------------------------------------------
# BMSFlashRecord (§3.5)
# ---------------------------------------------------------------------------

@bp.route("/integration-programs/<programId>/battery-packs/<packId>/bms-flash-records", methods=["POST"])
@require_roles("AssemblyLead")
def flash_pack(actor, programId, packId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    body = get_body(required=True)
    fw_id = as_str(req_field(body, "bms_firmware_id"), "bms_firmware_id")

    fw = db.firmwares.get(fw_id)
    if fw is None:
        raise err_firmware_not_found()
    require_program_open(program)
    if pack["assembly_status"] != "WELD_CERTIFIED":
        raise err_pack_not_weld_certified()
    # priority 12: cross-program referential integrity
    if fw["program_id"] != program["id"]:
        raise err_cross_program()
    # priority 14: firmware must be APPROVED (any other state rejects)
    if fw["status"] != "APPROVED":
        raise err_firmware_not_approved()

    prior = [r for r in db.flash_records.values() if r["battery_pack_id"] == pack["id"]]
    rec = new_row(common=False)
    rec.update(
        battery_pack_id=pack["id"],
        program_id=program["id"],
        bms_firmware_id=fw["id"],
        flashed_by_id=actor.user_id,
        flash_cycle_index=len(prior) + 1,
    )
    db.flash_records[rec["id"]] = rec

    pack["bms_firmware_id"] = fw["id"]
    pack["assembly_status"] = "BMS_FLASHED"
    touch(pack)
    return success_created(ser_flash_record(rec))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/bms-flash-records", methods=["GET"])
@require_roles()
def list_flash_records(actor, programId, packId):
    get_program(programId)
    pack = get_pack(programId, packId)
    rows = sorted_rows(
        [r for r in db.flash_records.values() if r["battery_pack_id"] == pack["id"]]
    )
    return success_list(rows, ser_flash_record)


# ---------------------------------------------------------------------------
# SafetyTestDossier (§3.6)
# ---------------------------------------------------------------------------

@bp.route("/integration-programs/<programId>/battery-packs/<packId>/safety-test-dossiers", methods=["POST"])
@require_roles("QualityEngineer")
def open_dossier(actor, programId, packId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    get_body()
    require_program_open(program)
    # initial open requires BMS_FLASHED; the retest cycle requires TEST_QUEUED
    if pack["assembly_status"] not in ("BMS_FLASHED", "TEST_QUEUED"):
        raise err_pack_not_bms_flashed()
    for d in db.dossiers.values():
        if d["battery_pack_id"] == pack["id"] and d["status"] in NON_TERMINAL_DOSSIER_STATES:
            raise err_dossier_already_open()

    prior = [d for d in db.dossiers.values() if d["battery_pack_id"] == pack["id"]]
    row = new_row()
    row.update(
        battery_pack_id=pack["id"],
        program_id=program["id"],
        dossier_cycle_index=len(prior) + 1,
        altitude_sim_kpa=None,
        thermal_cycles=None,
        vibration_minutes=None,
        shock_g_peak=None,
        external_short_circuit_ok=None,
        impact_crush_ok=None,
        overcharge_ok=None,
        forced_discharge_ok=None,
        provisional_un_score=None,
        final_un_score=None,
        outcome="PENDING",
        status="OPEN",
    )
    db.dossiers[row["id"]] = row

    pack["dossier_id"] = row["id"]
    if pack["assembly_status"] == "BMS_FLASHED":
        pack["assembly_status"] = "TEST_QUEUED"
    touch(pack)
    return success_created(ser_dossier(row))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/safety-test-dossiers", methods=["GET"])
@require_roles()
def list_dossiers(actor, programId, packId):
    get_program(programId)
    pack = get_pack(programId, packId)
    rows = sorted_rows(
        [d for d in db.dossiers.values() if d["battery_pack_id"] == pack["id"]]
    )
    return success_list(rows, ser_dossier)


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/safety-test-dossiers/<dossierId>", methods=["GET"])
@require_roles()
def get_one_dossier(actor, programId, packId, dossierId):
    get_program(programId)
    pack = get_pack(programId, packId)
    return success_object(ser_dossier(get_dossier(programId, pack["id"], dossierId)))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/safety-test-dossiers/<dossierId>", methods=["PUT"])
@require_roles("QualityEngineer")
def record_test_matrix(actor, programId, packId, dossierId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    dossier = get_dossier(programId, pack["id"], dossierId)
    body = get_body(required=True)
    # OCC field is required on this endpoint (§2.10)
    expected_pack_version = as_int(
        req_field(body, "expected_pack_version"), "expected_pack_version"
    )
    # type-check any provided test field; missing fields fall through to the
    # completeness check (ERR_INCOMPLETE_TEST_MATRIX, priority 10)
    values = {}
    if "altitude_sim_kpa" in body and body["altitude_sim_kpa"] is not None:
        values["altitude_sim_kpa"] = as_decimal(body["altitude_sim_kpa"], "altitude_sim_kpa")
    if "thermal_cycles" in body and body["thermal_cycles"] is not None:
        values["thermal_cycles"] = as_int(body["thermal_cycles"], "thermal_cycles")
    if "vibration_minutes" in body and body["vibration_minutes"] is not None:
        values["vibration_minutes"] = as_int(body["vibration_minutes"], "vibration_minutes")
    if "shock_g_peak" in body and body["shock_g_peak"] is not None:
        values["shock_g_peak"] = as_decimal(body["shock_g_peak"], "shock_g_peak")
    for f in ("external_short_circuit_ok", "impact_crush_ok", "overcharge_ok", "forced_discharge_ok"):
        if f in body and body[f] is not None:
            values[f] = as_bool(body[f], f)

    require_program_open(program)
    if dossier["status"] != "OPEN":
        raise err_dossier_not_open()
    # priority 10: all eight T1..T8 fields must be non-null
    merged = {f: values.get(f, dossier[f]) for f in DOSSIER_TEST_FIELDS}
    if any(merged[f] is None for f in DOSSIER_TEST_FIELDS):
        raise err_incomplete_test_matrix()
    # priority 22: OCC on BatteryPack.version
    if pack["version"] != expected_pack_version:
        raise err_stale_version()

    for f in DOSSIER_TEST_FIELDS:
        dossier[f] = merged[f]
    dossier["provisional_un_score"] = compute_un_score(dossier, "provisional")
    dossier["status"] = "TESTS_RECORDED"
    touch(dossier)
    touch(pack)  # recording the matrix bumps the pack version by 1
    return success_object(ser_dossier(dossier))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/safety-test-dossiers/<dossierId>/submit", methods=["POST"])
@require_roles("SafetyOfficer")
def submit_dossier(actor, programId, packId, dossierId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    dossier = get_dossier(programId, pack["id"], dossierId)
    get_body()
    require_program_open(program)
    if dossier["status"] != "TESTS_RECORDED":
        raise err_dossier_not_tests_recorded()
    if pack["assembly_status"] != "TEST_QUEUED":
        raise err_pack_not_test_queued()

    final = compute_un_score(dossier, "final")
    dossier["final_un_score"] = final
    if final >= UN_PASS_THRESHOLD:
        dossier["outcome"] = "PASS"
        dossier["status"] = "SUBMITTED"
        # shipping classification: derived from dossier outcome + chemistry
        # flag. No chemistry/equipment-containment input exists anywhere in the
        # domain model, so a PASS dossier deterministically classifies the
        # standalone Li-ion pack as UN3480.
        pack["shipping_classification"] = "UN3480"
        pack["assembly_status"] = "CLASSIFIED"
        touch(pack)
    else:
        dossier["outcome"] = "FAIL"
        dossier["status"] = "FAILED"
        # pack stays TEST_QUEUED; the retest cycle opens a fresh dossier
        decrement_risk(program, 5)
    touch(dossier)
    return success_object(ser_dossier(dossier))


@bp.route("/integration-programs/<programId>/battery-packs/<packId>/safety-test-dossiers/<dossierId>/approve", methods=["POST"])
@require_roles("SafetyOfficer")
def approve_dossier(actor, programId, packId, dossierId):
    program = get_program(programId)
    pack = get_pack(programId, packId)
    dossier = get_dossier(programId, pack["id"], dossierId)
    get_body()
    require_program_open(program)
    if dossier["status"] != "SUBMITTED":
        raise err_dossier_not_submitted()
    if dossier["outcome"] != "PASS":
        raise err_dossier_not_pass()
    if pack["assembly_status"] != "CLASSIFIED":
        raise err_pack_not_classified()

    dossier["status"] = "APPROVED"
    touch(dossier)
    pack["assembly_status"] = "READY_TO_STORE"
    touch(pack)
    return success_object(ser_dossier(dossier))
