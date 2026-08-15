"""Domain core: constants, row factories, serializers, calculations and
shared business logic for the Battery Pack Assembly & UN38.3 Compliance API.

All structural names (fields, enums, error ids) follow SCAFFOLD.yaml and the
PRD literally. Money/energy/score math uses Decimal; HALF_UP rounding is
applied as the final step of every calculation (PRD §2.9)."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import (
    err_program_not_found, err_lot_not_found, err_bom_not_found,
    err_pack_not_found, err_weld_record_not_found, err_firmware_not_found,
    err_dossier_not_found, err_location_not_found, err_placement_not_found,
    err_shipment_not_found, err_rma_not_found, err_recall_not_found,
    err_program_not_open, err_pack_under_recall,
)
from util import format_ts, num, round_half_up

# ---------------------------------------------------------------------------
# Constants (PRD §3, calculations table)
# ---------------------------------------------------------------------------

WELD_PROFILES = ("WELD_PROFILE_A", "WELD_PROFILE_B", "WELD_PROFILE_C")
WELD_BASE_DOSE = {
    "WELD_PROFILE_A": Decimal("12.0"),
    "WELD_PROFILE_B": Decimal("18.0"),
    "WELD_PROFILE_C": Decimal("25.0"),
}
WELD_CEILING = {
    "WELD_PROFILE_A": Decimal("450.0"),
    "WELD_PROFILE_B": Decimal("700.0"),
    "WELD_PROFILE_C": Decimal("1050.0"),
}
NOMINAL_FORCE_N = Decimal("30.0")
FORCE_FACTOR_MIN = Decimal("0.7")
FORCE_FACTOR_MAX = Decimal("1.4")

UN_WEIGHTS = {"T1": 10, "T2": 15, "T3": 12, "T4": 13, "T5": 15, "T6": 15, "T7": 10, "T8": 10}
UN_PASS_THRESHOLD = Decimal("85.0")
UN_REF_ALT_KPA = Decimal("11.6")
UN_REF_THERMAL_CYCLES = Decimal("10")
UN_REF_VIBRATION_MIN = Decimal("180")
UN_REF_SHOCK_G = Decimal("150")

SOC_BANDS = ("SOC_LOW", "SOC_MID", "SOC_HIGH")
SOC_LOW_MAX_EXCLUSIVE = Decimal("30")
SOC_MID_MAX_INCLUSIVE = Decimal("60")
HYSTERESIS_PERCENT = Decimal("2.0")
SAFE_DISCHARGE_MAX_PERCENT = Decimal("30.0")

FIRE_ZONES = ("ZONE_A", "ZONE_B", "ZONE_C", "ZONE_ISOLATION")

UN_CLASS_CODES = ("UN3480", "UN3481", "UN3090", "UN3091")
DG_MULTIPLIER = {
    "UN3480": Decimal("1.25"),
    "UN3481": Decimal("1.15"),
    "UN3090": Decimal("1.35"),
    "UN3091": Decimal("1.20"),
}
CARRIER_TIERS = (
    (Decimal("0"), Decimal("500"), Decimal("0.12")),
    (Decimal("500"), Decimal("2000"), Decimal("0.09")),
    (Decimal("2000"), Decimal("5000"), Decimal("0.06")),
    (Decimal("5000"), None, Decimal("0.04")),
)
WEIGHT_SURCHARGE_CENTS_PER_KG = Decimal("40")

REASON_CODES = ("DEFECT", "WARRANTY", "OVERSTOCK", "RECALL_RETURN")
SEVERITIES = ("CLASS_I", "CLASS_II", "CLASS_III")
SEVERITY_WEIGHT = {"CLASS_I": 15, "CLASS_II": 8, "CLASS_III": 3}

INSPECTION_OUTCOMES = ("PASS", "FAIL_SOFT", "FAIL_HARD")
FIRMWARE_DECISIONS = ("APPROVE", "REJECT", "REVOKE")

# pack assembly states at/after which a firmware is considered "in use"
FIRMWARE_IN_USE_STATES = ("TEST_QUEUED", "CLASSIFIED", "READY_TO_STORE")
NON_TERMINAL_DOSSIER_STATES = ("OPEN", "TESTS_RECORDED", "SUBMITTED")
OPEN_SHIPMENT_STATES = ("TENDERED", "CARRIER_ACCEPTED", "IN_TRANSIT")


# ---------------------------------------------------------------------------
# Row plumbing (PRD §2.4)
# ---------------------------------------------------------------------------

def new_row(common=True):
    """Base fields. common=True -> id/created_at/updated_at/version;
    common=False (immutable event records) -> id/created_at only."""
    row = {"id": db.new_id(), "created_at": clock.now(), "_seq": db.next_seq()}
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Any mutation refreshes updated_at and increments version (§2.4)."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = clock.now()


def sorted_rows(rows):
    """Lists sort by created_at ascending (§2.3); _seq breaks ties stably."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Resolution helpers (§2.5: nested paths validate left to right; a child that
# does not belong to its path parent is a 404 of the child's family)
# ---------------------------------------------------------------------------

def get_program(program_id):
    row = db.programs.get(program_id)
    if row is None:
        raise err_program_not_found()
    return row


def _child(collection, cid, program_id, not_found_err, parent_field=None, parent_id=None):
    row = collection.get(cid)
    if row is None or row.get("program_id") != program_id:
        raise not_found_err()
    if parent_field is not None and row.get(parent_field) != parent_id:
        raise not_found_err()
    return row


def get_lot(program_id, lot_id):
    return _child(db.cell_lots, lot_id, program_id, err_lot_not_found)


def get_bom(program_id, bom_id):
    return _child(db.boms, bom_id, program_id, err_bom_not_found)


def get_pack(program_id, pack_id):
    return _child(db.packs, pack_id, program_id, err_pack_not_found)


def get_weld_record(program_id, pack_id, record_id):
    return _child(db.weld_records, record_id, program_id, err_weld_record_not_found,
                  parent_field="battery_pack_id", parent_id=pack_id)


def get_firmware(program_id, fw_id):
    return _child(db.firmwares, fw_id, program_id, err_firmware_not_found)


def get_dossier(program_id, pack_id, dossier_id):
    return _child(db.dossiers, dossier_id, program_id, err_dossier_not_found,
                  parent_field="battery_pack_id", parent_id=pack_id)


def get_location(program_id, location_id):
    return _child(db.locations, location_id, program_id, err_location_not_found)


def get_placement(program_id, placement_id):
    return _child(db.placements, placement_id, program_id, err_placement_not_found)


def get_shipment(program_id, shipment_id):
    return _child(db.shipments, shipment_id, program_id, err_shipment_not_found)


def get_rma(program_id, rma_id):
    return _child(db.rmas, rma_id, program_id, err_rma_not_found)


def get_recall(program_id, recall_id):
    return _child(db.recalls, recall_id, program_id, err_recall_not_found)


def require_program_open(program):
    """Priority 4 posture gate: any child-creating or child-mutating call
    requires the owning program OPEN (§2.6)."""
    if program["status"] != "OPEN":
        raise err_program_not_open()


def pack_under_active_recall(pack):
    """True iff the pack is captured by a recall whose status is ACTIVE."""
    rid = pack.get("active_recall_id")
    if not rid:
        return False
    recall = db.recalls.get(rid)
    return recall is not None and recall["status"] == "ACTIVE"


def raise_if_pack_under_recall(pack):
    if pack_under_active_recall(pack):
        raise err_pack_under_recall()


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD table 1.3 / PRD §3)
# ---------------------------------------------------------------------------

def compute_heat_dose(weld_count, current_amps, pulse_ms, electrode_force_n, profile):
    """welding_heat_dose: raw joules = count * amps * (pulse_ms/1000) * base;
    force factor 1 + (F-30)/100 clamped to [0.7, 1.4]; HALF_UP 2dp LAST."""
    force_factor = Decimal("1.0") + (electrode_force_n - NOMINAL_FORCE_N) / Decimal("100")
    if force_factor < FORCE_FACTOR_MIN:
        force_factor = FORCE_FACTOR_MIN
    elif force_factor > FORCE_FACTOR_MAX:
        force_factor = FORCE_FACTOR_MAX
    raw = (
        Decimal(weld_count)
        * current_amps
        * (Decimal(pulse_ms) / Decimal("1000"))
        * WELD_BASE_DOSE[profile]
    )
    return round_half_up(raw * force_factor, 2)


def compute_nominal_energy_wh(cells_required, rated_capacity_mah):
    """nominal_energy_wh = cells_required * rated_capacity_mah * 3.6 / 1000 (2dp)."""
    return round_half_up(
        Decimal(cells_required) * Decimal(rated_capacity_mah) * Decimal("3.6") / Decimal("1000"),
        2,
    )


def _clamp01(x):
    if x < 0:
        return Decimal("0")
    if x > 1:
        return Decimal("1")
    return x


def compute_un_score(dossier, variant):
    """un38_3_composite_score. variant 'provisional': null boolean -> 0.5;
    variant 'final': null boolean -> 0.0 and ANY false boolean zeroes the
    entire score (fail-fast). HALF_UP 2dp."""
    s_t1 = _clamp01(dossier["altitude_sim_kpa"] / UN_REF_ALT_KPA)
    s_t2 = _clamp01(Decimal(dossier["thermal_cycles"]) / UN_REF_THERMAL_CYCLES)
    s_t3 = _clamp01(Decimal(dossier["vibration_minutes"]) / UN_REF_VIBRATION_MIN)
    s_t4 = _clamp01(dossier["shock_g_peak"] / UN_REF_SHOCK_G)

    bool_fields = (
        ("T5", "external_short_circuit_ok"),
        ("T6", "impact_crush_ok"),
        ("T7", "overcharge_ok"),
        ("T8", "forced_discharge_ok"),
    )
    if variant == "final":
        for _, fname in bool_fields:
            if dossier[fname] is False:
                return Decimal("0.0")

    base = (
        Decimal(UN_WEIGHTS["T1"]) * s_t1
        + Decimal(UN_WEIGHTS["T2"]) * s_t2
        + Decimal(UN_WEIGHTS["T3"]) * s_t3
        + Decimal(UN_WEIGHTS["T4"]) * s_t4
    )
    for tname, fname in bool_fields:
        v = dossier[fname]
        if v is None:
            sub = Decimal("0.5") if variant == "provisional" else Decimal("0.0")
        elif v:
            sub = Decimal("1")
        else:
            sub = Decimal("0")
        base += Decimal(UN_WEIGHTS[tname]) * sub
    return round_half_up(base, 2)


def soc_band_plain(soc):
    """soc_band_assignment plain variant: <30 LOW, 30..60 MID, >60 HIGH."""
    if soc < SOC_LOW_MAX_EXCLUSIVE:
        return "SOC_LOW"
    if soc <= SOC_MID_MAX_INCLUSIVE:
        return "SOC_MID"
    return "SOC_HIGH"


def soc_band_after_discharge(current_band, soc, firmware):
    """soc_band after a safe-discharge event. The hysteresis variant applies
    only when the flashed firmware supports it (§3.7): boundaries widen by
    ±2.0 against the direction of travel — MID leaves downwards only below
    28.0, upwards only above 62.0; LOW holds until 32.0; HIGH holds above 58.0."""
    if firmware is None or not firmware.get("supports_soc_hysteresis"):
        return soc_band_plain(soc)
    h = HYSTERESIS_PERCENT
    if current_band == "SOC_LOW":
        if soc < SOC_LOW_MAX_EXCLUSIVE + h:
            return "SOC_LOW"
        return "SOC_HIGH" if soc > SOC_MID_MAX_INCLUSIVE + h else "SOC_MID"
    if current_band == "SOC_MID":
        if soc < SOC_LOW_MAX_EXCLUSIVE - h:
            return "SOC_LOW"
        if soc > SOC_MID_MAX_INCLUSIVE + h:
            return "SOC_HIGH"
        return "SOC_MID"
    # SOC_HIGH
    if soc > SOC_MID_MAX_INCLUSIVE - h:
        return "SOC_HIGH"
    if soc < SOC_LOW_MAX_EXCLUSIVE - h:
        return "SOC_LOW"
    return "SOC_MID"


def compute_carrier_charge_cents(total_wh, declared_weight_kg, un_class_code):
    """carrier_acceptance_charge: tiered Wh component + weight surcharge,
    DG multiplier applied LAST, HALF_UP to integer cents."""
    wh_component = Decimal("0")
    for lo, hi, rate in CARRIER_TIERS:
        if hi is None:
            in_tier = max(Decimal("0"), total_wh - lo)
        else:
            in_tier = max(Decimal("0"), min(total_wh, hi) - lo)
        wh_component += in_tier * rate
    weight_component = declared_weight_kg * WEIGHT_SURCHARGE_CENTS_PER_KG / Decimal("100")
    total_dollars = (wh_component + weight_component) * DG_MULTIPLIER[un_class_code]
    cents = (total_dollars * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def mint_serial_number(program):
    """SN-<program_code>-<zero-padded 6-digit counter>, per program."""
    n = program.get("_serial_next", 1)
    program["_serial_next"] = n + 1
    return "SN-%s-%06d" % (program["program_code"], n)


def locked_committed_cells(lot_id):
    """Sum of cells_required across all is_locked PackBOMs drawing on a lot."""
    total = 0
    for bom in db.boms.values():
        if bom["cell_lot_id"] == lot_id and bom["is_locked"]:
            total += bom["cells_required"]
    return total


def check_lot_depletion(lot):
    """ACCEPTED -> DEPLETED when locked-BOM commitment reaches cell_count (§3.2)."""
    if lot["status"] == "ACCEPTED" and locked_committed_cells(lot["id"]) >= lot["cell_count"]:
        lot["status"] = "DEPLETED"
        touch(lot)


def active_placement_for_pack(pack_id):
    for p in db.placements.values():
        if p["battery_pack_id"] == pack_id and p["status"] in ("STAGED", "STORED"):
            return p
    return None


def release_placement(placement, pack):
    """Shared release side effects: placement -> RELEASED, both watt-hour
    ledgers decremented, pack storage link cleared (§2.8, §3.7)."""
    location = db.locations[placement["storage_location_id"]]
    program = db.programs[placement["program_id"]]
    energy = pack["pack_energy_wh"]
    placement["status"] = "RELEASED"
    placement["released_at_utc"] = clock.now()
    touch(placement)
    location["wh_occupied"] = round_half_up(location["wh_occupied"] - energy, 2)
    touch(location)
    program["wh_committed"] = round_half_up(program["wh_committed"] - energy, 2)
    touch(program)
    pack["storage_location_id"] = None


def decrement_risk(program, amount):
    """compliance_risk_index only ever moves downward, floored at 0 (§2.7)."""
    program["compliance_risk_index"] = max(0, program["compliance_risk_index"] - amount)
    touch(program)


def recall_capture_set(recall):
    """recall_capture_set: union of lot/bom/serial-prefix matches, deduped by
    pack id, excluding packs already in assembly_status RECALLED."""
    captured = {}
    for pack in db.packs.values():
        if pack["program_id"] != recall["program_id"]:
            continue
        if pack["assembly_status"] == "RECALLED":
            continue
        hit = False
        if recall.get("scope_lot_id") and pack["cell_lot_id"] == recall["scope_lot_id"]:
            hit = True
        if recall.get("scope_bom_id") and pack["bom_id"] == recall["scope_bom_id"]:
            hit = True
        if recall.get("scope_serial_prefix") and pack["serial_number"].startswith(
            recall["scope_serial_prefix"]
        ):
            hit = True
        if hit:
            captured[pack["id"]] = pack
    return captured


# ---------------------------------------------------------------------------
# Serializers — field sets exactly per SCAFFOLD table 1.1. Internal bookkeeping
# keys are underscore-prefixed and stripped here. Immutable event records
# (§2.4) carry only id + created_at, never updated_at/version.
# ---------------------------------------------------------------------------

def _common(row):
    return {
        "id": row["id"],
        "created_at": format_ts(row["created_at"]),
        "updated_at": format_ts(row["updated_at"]),
        "version": row["version"],
    }


def ser_program(r):
    out = _common(r)
    out.update(
        program_code=r["program_code"],
        compliance_risk_index=r["compliance_risk_index"],
        storage_capacity_wh=r["storage_capacity_wh"],
        wh_committed=num(r["wh_committed"], 2),
        wh_available=num(r["storage_capacity_wh"] - r["wh_committed"], 2),
        recall_count=r["recall_count"],
        status=r["status"],
    )
    return out


def ser_cell_lot(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        lot_code=r["lot_code"],
        cell_count=r["cell_count"],
        rated_capacity_mah=r["rated_capacity_mah"],
        receiving_soc_percent=num(r["receiving_soc_percent"], 1),
        measured_soc_percent=num(r["measured_soc_percent"], 1),
        quarantine_cycle_count=r["quarantine_cycle_count"],
        status=r["status"],
    )
    return out


def ser_inspection(r):
    return {
        "id": r["id"],
        "created_at": format_ts(r["created_at"]),
        "cell_lot_id": r["cell_lot_id"],
        "program_id": r["program_id"],
        "inspector_id": r["inspector_id"],
        "measured_soc_percent": num(r["measured_soc_percent"], 1),
        "measured_voltage_v": num(r["measured_voltage_v"], 2),
        "visual_defect_count": r["visual_defect_count"],
        "outcome": r["outcome"],
    }


def ser_bom(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        bom_code=r["bom_code"],
        cell_lot_id=r["cell_lot_id"],
        cells_required=r["cells_required"],
        series_count=r["series_count"],
        parallel_count=r["parallel_count"],
        nominal_energy_wh=num(r["nominal_energy_wh"], 2),
        welding_profile=r["welding_profile"],
        is_locked=r["is_locked"],
        version_note=r["version_note"],
    )
    return out


def ser_pack(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        serial_number=r["serial_number"],
        bom_id=r["bom_id"],
        cell_lot_id=r["cell_lot_id"],
        pack_energy_wh=num(r["pack_energy_wh"], 2),
        assembly_status=r["assembly_status"],
        logistics_status=r["logistics_status"],
        soc_percent=num(r["soc_percent"], 1),
        soc_band=r["soc_band"],
        shipping_classification=r["shipping_classification"],
        welding_heat_dose_j=num(r["welding_heat_dose_j"], 2),
        bms_firmware_id=r["bms_firmware_id"],
        dossier_id=r["dossier_id"],
        storage_location_id=r["storage_location_id"],
        active_recall_id=r["active_recall_id"],
        is_safe_discharged=r["is_safe_discharged"],
        disposition=r["disposition"],
    )
    return out


def ser_weld_record(r):
    return {
        "id": r["id"],
        "created_at": format_ts(r["created_at"]),
        "battery_pack_id": r["battery_pack_id"],
        "program_id": r["program_id"],
        "operator_id": r["operator_id"],
        "certified_by_id": r["certified_by_id"],
        "weld_count": r["weld_count"],
        "current_amps": num(r["current_amps"], 1),
        "pulse_ms": r["pulse_ms"],
        "electrode_force_n": num(r["electrode_force_n"], 1),
        "weld_profile_used": r["weld_profile_used"],
        "heat_dose_j": num(r["heat_dose_j"], 2),
        "is_certified": r["is_certified"],
    }


def ser_firmware(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        firmware_version=r["firmware_version"],
        binary_sha256=r["binary_sha256"],
        supports_soc_hysteresis=r["supports_soc_hysteresis"],
        approval_record_id=r["approval_record_id"],
        status=r["status"],
    )
    return out


def ser_approval(r):
    return {
        "id": r["id"],
        "created_at": format_ts(r["created_at"]),
        "bms_firmware_id": r["bms_firmware_id"],
        "program_id": r["program_id"],
        "approver_id": r["approver_id"],
        "decision": r["decision"],
        "rationale": r["rationale"],
    }


def ser_flash_record(r):
    return {
        "id": r["id"],
        "created_at": format_ts(r["created_at"]),
        "battery_pack_id": r["battery_pack_id"],
        "program_id": r["program_id"],
        "bms_firmware_id": r["bms_firmware_id"],
        "flashed_by_id": r["flashed_by_id"],
        "flash_cycle_index": r["flash_cycle_index"],
    }


def ser_dossier(r):
    out = _common(r)
    out.update(
        battery_pack_id=r["battery_pack_id"],
        program_id=r["program_id"],
        dossier_cycle_index=r["dossier_cycle_index"],
        altitude_sim_kpa=num(r["altitude_sim_kpa"], 2),
        thermal_cycles=r["thermal_cycles"],
        vibration_minutes=r["vibration_minutes"],
        shock_g_peak=num(r["shock_g_peak"], 2),
        external_short_circuit_ok=r["external_short_circuit_ok"],
        impact_crush_ok=r["impact_crush_ok"],
        overcharge_ok=r["overcharge_ok"],
        forced_discharge_ok=r["forced_discharge_ok"],
        provisional_un_score=num(r["provisional_un_score"], 2),
        final_un_score=num(r["final_un_score"], 2),
        outcome=r["outcome"],
        status=r["status"],
    )
    return out


def ser_location(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        location_code=r["location_code"],
        fire_zone=r["fire_zone"],
        capacity_wh=r["capacity_wh"],
        wh_occupied=num(r["wh_occupied"], 2),
        wh_headroom=num(Decimal(r["capacity_wh"]) - r["wh_occupied"], 2),
        accepts_soc_band=list(r["accepts_soc_band"]),
    )
    return out


def ser_placement(r):
    out = _common(r)
    out.update(
        storage_location_id=r["storage_location_id"],
        battery_pack_id=r["battery_pack_id"],
        program_id=r["program_id"],
        staged_at_utc=format_ts(r["staged_at_utc"]),
        stored_at_utc=format_ts(r["stored_at_utc"]),
        released_at_utc=format_ts(r["released_at_utc"]),
        status=r["status"],
    )
    return out


def ser_shipment(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        carrier_code=r["carrier_code"],
        un_class_code=r["un_class_code"],
        declared_weight_kg=num(r["declared_weight_kg"], 2),
        total_pack_count=r["total_pack_count"],
        total_wh=num(r["total_wh"], 2),
        carrier_charge_cents=r["carrier_charge_cents"],
        status=r["status"],
    )
    return out


def ser_link(r):
    return {
        "id": r["id"],
        "created_at": format_ts(r["created_at"]),
        "transport_shipment_id": r["transport_shipment_id"],
        "battery_pack_id": r["battery_pack_id"],
        "program_id": r["program_id"],
        "attached_at_utc": format_ts(r["attached_at_utc"]),
    }


def ser_rma(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        battery_pack_id=r["battery_pack_id"],
        reason_code=r["reason_code"],
        requested_by_id=r["requested_by_id"],
        approved_by_id=r["approved_by_id"],
        target_soc_percent=num(r["target_soc_percent"], 1),
        actual_soc_after_discharge=num(r["actual_soc_after_discharge"], 1),
        status=r["status"],
    )
    return out


def ser_recall(r):
    out = _common(r)
    out.update(
        program_id=r["program_id"],
        recall_code=r["recall_code"],
        scope_lot_id=r["scope_lot_id"],
        scope_bom_id=r["scope_bom_id"],
        scope_serial_prefix=r["scope_serial_prefix"],
        packs_in_scope=r["packs_in_scope"],
        packs_contained=r["packs_contained"],
        severity=r["severity"],
        status=r["status"],
    )
    return out
