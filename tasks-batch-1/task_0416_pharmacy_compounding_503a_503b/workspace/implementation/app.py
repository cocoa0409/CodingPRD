"""Pharmacy Compounding (503A/503B) REST API — Flask entry point.

All resources mount under /pharmacy-compounding. Storage is in-memory only and
starts empty on every boot (no seeding). The per-test-server harness re-launches
this process before each test.

Validation precedence on every request (PRD §1.4 / §3.11):
  1. auth headers present + known role        (401)
  2. role permitted for the operation         (403)
  3. path-id existence, left-to-right         (404)
  4. body FK existence within facility        (422)
  5. structural body validation               (400)  [interleaved as fields are read]
  6. state / OCC / business rules             (409/412/422/...)
"""
import os

from flask import Flask, request

import db
import calculations as calc
import store
import timeutil
from errors import ApiError
from middleware import get_user_context, require_roles, ALL_ROLES
from response import success, error
import validation as V

app = Flask(__name__)
app.url_map.strict_slashes = False

PREFIX = "/pharmacy-compounding"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error("ERR_INVALID_REQUEST", "Resource path not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 400)


# ---------------------------------------------------------------------------
# Lookup helpers (path-id existence, 404)
# ---------------------------------------------------------------------------
def get_facility_or_404(fid):
    f = db.facilities.get(fid)
    if f is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND", "Facility not found")
    return f


def get_mfr_or_404(mid):
    m = db.master_formulation_records.get(mid)
    if m is None:
        raise ApiError("ERR_MFR_NOT_FOUND", "Master formulation record not found")
    return m


def get_lot_or_404(lid):
    l = db.ingredient_lots.get(lid)
    if l is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Ingredient lot not found")
    return l


def get_prescription_or_404(pid):
    p = db.prescriptions.get(pid)
    if p is None:
        raise ApiError("ERR_PRESCRIPTION_NOT_FOUND", "Prescription not found")
    return p


def get_batch_or_404(bid):
    b = db.compounding_batches.get(bid)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", "Compounding batch not found")
    return b


def get_usage_or_404(uid):
    u = db.batch_ingredient_usages.get(uid)
    if u is None:
        raise ApiError("ERR_INVALID_REQUEST", "Batch ingredient usage not found", 404)
    return u


def get_qc_or_404(qid):
    q = db.quality_control_tests.get(qid)
    if q is None:
        raise ApiError("ERR_QC_TEST_NOT_FOUND", "Quality control test not found")
    return q


def get_finished_or_404(fpid):
    fp = db.finished_preparations.get(fpid)
    if fp is None:
        raise ApiError("ERR_FINISHED_PREPARATION_NOT_FOUND", "Finished preparation not found")
    return fp


def get_dispense_or_404(did):
    d = db.dispenses.get(did)
    if d is None:
        raise ApiError("ERR_INVALID_REQUEST", "Dispense not found", 404)
    return d


def get_ledger_or_404(alid):
    le = db.anticipatory_ledgers.get(alid)
    if le is None:
        raise ApiError("ERR_INVALID_REQUEST", "Anticipatory ledger not found", 404)
    return le


def get_env_log_or_404(eid):
    e = db.environmental_logs.get(eid)
    if e is None:
        raise ApiError("ERR_ENVIRONMENTAL_LOG_NOT_FOUND", "Environmental log not found")
    return e


def get_recall_or_404(rid):
    r = db.recalls.get(rid)
    if r is None:
        raise ApiError("ERR_RECALL_NOT_FOUND", "Recall not found")
    return r


# ---------------------------------------------------------------------------
# Auth gate — call at the top of every handler
# ---------------------------------------------------------------------------
def authorize(allowed_roles):
    user_id, role = get_user_context()
    require_roles(role, allowed_roles)
    return user_id, role


def list_response(records, serializer):
    limit, offset = V.parse_pagination()
    records = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    page, meta = V.paginate(records, limit, offset)
    return success([serializer(r) for r in page], status=200, pagination=meta)


# ===========================================================================
# FACILITIES
# ===========================================================================
@app.route(PREFIX + "/facilities", methods=["POST"])
def create_facility():
    authorize({"SystemAdmin"})
    body = V.get_json_body()
    name = V.require_str(body, "name")
    registration_type = V.require_enum(body, "registration_type", {"503A", "503B"})
    state_code = V.require_str(body, "state_code")
    with db.lock:
        rec = store.init_common({
            "name": name,
            "registration_type": registration_type,
            "state_code": state_code,
            "current_utc": timeutil.EPOCH_ISO,
        })
        db.facilities[rec["id"]] = rec
        return success(store.serialize_facility(rec), status=201)


@app.route(PREFIX + "/facilities", methods=["GET"])
def list_facilities():
    authorize(ALL_ROLES)
    return list_response(list(db.facilities.values()), store.serialize_facility)


@app.route(PREFIX + "/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    authorize(ALL_ROLES)
    f = get_facility_or_404(fid)
    return success(store.serialize_facility(f), status=200)


@app.route(PREFIX + "/facilities/<fid>/_clock/set", methods=["POST"])
def set_clock(fid):
    authorize({"SystemAdmin"})
    f = get_facility_or_404(fid)
    body = V.get_json_body()
    to_iso = V.require_str(body, "to_iso8601")
    parsed = timeutil.parse_iso(to_iso)  # validates format
    with db.lock:
        f["current_utc"] = timeutil.format_iso(parsed)
        store.touch(f)
        return success(store.serialize_facility(f), status=200)


# ===========================================================================
# MASTER FORMULATION RECORDS
# ===========================================================================
@app.route(PREFIX + "/master-formulation-records", methods=["POST"])
def create_mfr():
    authorize({"CompoundingPharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    name = V.require_str(body, "name")
    dosage_form = V.require_enum(body, "dosage_form", {
        "ORAL_SOLID", "ORAL_LIQUID", "TOPICAL", "NONSTERILE_OTHER",
        "STERILE_AQUEOUS", "STERILE_NONAQUEOUS",
    })
    default_bud = V.require_int(body, "default_bud_days_nonsterile")
    if default_bud < 1:
        raise ApiError("ERR_INVALID_REQUEST", "default_bud_days_nonsterile must be >= 1")
    theoretical = V.require_int(body, "theoretical_yield_units")
    if theoretical < 1:
        raise ApiError("ERR_INVALID_REQUEST", "theoretical_yield_units must be >= 1")
    anticipatory_max = V.require_int(body, "anticipatory_max_units")
    if anticipatory_max < 0:
        raise ApiError("ERR_INVALID_REQUEST", "anticipatory_max_units must be >= 0")
    window_days = V.optional_int(body, "anticipatory_window_days", 30)
    if window_days < 1:
        raise ApiError("ERR_INVALID_REQUEST", "anticipatory_window_days must be >= 1")

    with db.lock:
        # Body FK existence within facility (422)
        if facility_id not in db.facilities:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")

        is_sterile = dosage_form in calc.STERILE_FORMS
        rec = store.init_common({
            "facility_id": facility_id,
            "name": name,
            "dosage_form": dosage_form,
            "is_sterile": is_sterile,
            "default_bud_days_nonsterile": default_bud,
            "theoretical_yield_units": theoretical,
            "anticipatory_window_days": window_days,
            "anticipatory_max_units": anticipatory_max,
            "status": "ACTIVE",
        })
        db.master_formulation_records[rec["id"]] = rec
        # Create exactly one anticipatory ledger bound to this MFR.
        ledger = store.init_common({
            "master_formulation_record_id": rec["id"],
            "window_start_utc": None,
            "consumed_units": 0,
            "remaining_units": anticipatory_max,
        })
        store.recompute_ledger(ledger)
        db.anticipatory_ledgers[ledger["id"]] = ledger
        return success(store.serialize_mfr(rec), status=201)


@app.route(PREFIX + "/master-formulation-records", methods=["GET"])
def list_mfrs():
    authorize(ALL_ROLES)
    records = list(db.master_formulation_records.values())
    fid = request.args.get("facility_id")
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    return list_response(records, store.serialize_mfr)


@app.route(PREFIX + "/master-formulation-records/<mid>", methods=["GET"])
def get_mfr(mid):
    authorize(ALL_ROLES)
    m = get_mfr_or_404(mid)
    return success(store.serialize_mfr(m), status=200)


@app.route(PREFIX + "/master-formulation-records/<mid>/retire", methods=["POST"])
def retire_mfr(mid):
    authorize({"CompoundingPharmacist"})
    m = get_mfr_or_404(mid)
    with db.lock:
        m["status"] = "RETIRED"
        store.touch(m)
        return success(store.serialize_mfr(m), status=200)


@app.route(PREFIX + "/master-formulation-records/<mid>/anticipatory-ledger", methods=["GET"])
def get_mfr_ledger(mid):
    authorize(ALL_ROLES)
    get_mfr_or_404(mid)
    with db.lock:
        ledger = store.ledger_for_mfr(mid)
        if ledger is None:
            raise ApiError("ERR_INVALID_REQUEST", "No ledger for MFR", 404)
        store.recompute_ledger(ledger)
        return success(store.serialize_ledger(ledger), status=200)


@app.route(PREFIX + "/anticipatory-ledgers", methods=["GET"])
def list_ledgers():
    authorize(ALL_ROLES)
    records = list(db.anticipatory_ledgers.values())
    mfr_id = request.args.get("master_formulation_record_id")
    if mfr_id:
        records = [r for r in records if r["master_formulation_record_id"] == mfr_id]
    with db.lock:
        for r in records:
            store.recompute_ledger(r)
    return list_response(records, store.serialize_ledger)


@app.route(PREFIX + "/anticipatory-ledgers/<alid>", methods=["GET"])
def get_ledger(alid):
    authorize(ALL_ROLES)
    le = get_ledger_or_404(alid)
    with db.lock:
        store.recompute_ledger(le)
        return success(store.serialize_ledger(le), status=200)


# ===========================================================================
# INGREDIENT LOTS
# ===========================================================================
@app.route(PREFIX + "/ingredient-lots", methods=["POST"])
def create_lot():
    authorize({"CompoundingPharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    component_name = V.require_str(body, "component_name")
    lot_number = V.require_str(body, "lot_number")
    labeled_potency = V.require_number(body, "labeled_potency_pct")
    if not (0 < labeled_potency <= 200):
        raise ApiError("ERR_INVALID_REQUEST", "labeled_potency_pct must be in (0, 200]")
    initial_grams = V.require_number(body, "initial_grams")
    if initial_grams <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "initial_grams must be > 0")
    expiration_utc = V.require_str(body, "expiration_utc")
    expiry_dt = timeutil.parse_iso(expiration_utc)
    endotoxin = V.optional_number(body, "endotoxin_eu_per_mg", 0)
    if endotoxin < 0:
        raise ApiError("ERR_INVALID_REQUEST", "endotoxin_eu_per_mg must be >= 0")
    parent_lot_id = V.optional_str(body, "parent_lot_id", None)

    with db.lock:
        if facility_id not in db.facilities:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")
        if parent_lot_id is not None:
            parent = db.ingredient_lots.get(parent_lot_id)
            if parent is None or parent["facility_id"] != facility_id:
                raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "parent_lot_id not found in facility")

        rec = store.init_common({
            "facility_id": facility_id,
            "parent_lot_id": parent_lot_id,
            "component_name": component_name,
            "lot_number": lot_number,
            "labeled_potency_pct": labeled_potency,
            "endotoxin_eu_per_mg": endotoxin,
            "initial_grams": initial_grams,
            "remaining_grams": calc.remaining_grams(initial_grams, 0),
            "expiration_utc": timeutil.format_iso(expiry_dt),
            "status": "AVAILABLE",
        })
        db.ingredient_lots[rec["id"]] = rec
        return success(store.serialize_lot(rec), status=201)


@app.route(PREFIX + "/ingredient-lots", methods=["GET"])
def list_lots():
    authorize(ALL_ROLES)
    records = list(db.ingredient_lots.values())
    fid = request.args.get("facility_id")
    parent = request.args.get("parent_lot_id")
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    if parent:
        records = [r for r in records if r.get("parent_lot_id") == parent]
    with db.lock:
        for r in records:
            store.refresh_lot_expiry(r)
    return list_response(records, store.serialize_lot)


@app.route(PREFIX + "/ingredient-lots/<lid>", methods=["GET"])
def get_lot(lid):
    authorize(ALL_ROLES)
    l = get_lot_or_404(lid)
    with db.lock:
        store.refresh_lot_expiry(l)
        return success(store.serialize_lot(l), status=200)


@app.route(PREFIX + "/ingredient-lots/<lid>/release-quarantine", methods=["POST"])
def release_quarantine_lot(lid):
    authorize({"QualityAssurancePharmacist"})
    l = get_lot_or_404(lid)
    with db.lock:
        if l["status"] != "QUARANTINED":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Lot is not QUARANTINED")
        l["status"] = "AVAILABLE"
        store.touch(l)
        return success(store.serialize_lot(l), status=200)


# ===========================================================================
# ENVIRONMENTAL LOGS
# ===========================================================================
@app.route(PREFIX + "/environmental-logs", methods=["POST"])
def create_env_log():
    authorize({"QualityAssurancePharmacist", "CompoundingPharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    usp_chapter = V.require_enum(body, "usp_chapter", {"USP_795", "USP_797"})
    reading_type = V.require_enum(body, "reading_type", {
        "ISO_PARTICLE_COUNT", "VIABLE_AIR_CFU", "SURFACE_CFU", "ROOM_TEMP_C", "ROOM_HUMIDITY_PCT",
    })
    measured_value = V.require_number(body, "measured_value")
    action_limit = V.require_number(body, "action_limit")

    with db.lock:
        facility = db.facilities.get(facility_id)
        if facility is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")
        in_spec = measured_value <= action_limit
        rid = db.new_id()
        rec = {
            "id": rid,
            "facility_id": facility_id,
            "usp_chapter": usp_chapter,
            "reading_type": reading_type,
            "measured_value": measured_value,
            "action_limit": action_limit,
            "in_spec": in_spec,
            "reading_utc": facility["current_utc"],
            "created_at": db.now_iso(),
        }
        db.environmental_logs[rid] = rec
        return success(store.serialize_env_log(rec), status=201)


@app.route(PREFIX + "/environmental-logs", methods=["GET"])
def list_env_logs():
    authorize(ALL_ROLES)
    records = list(db.environmental_logs.values())
    fid = request.args.get("facility_id")
    chapter = request.args.get("usp_chapter")
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    if chapter:
        records = [r for r in records if r["usp_chapter"] == chapter]
    return list_response(records, store.serialize_env_log)


@app.route(PREFIX + "/environmental-logs/<eid>", methods=["GET"])
def get_env_log(eid):
    authorize(ALL_ROLES)
    e = get_env_log_or_404(eid)
    return success(store.serialize_env_log(e), status=200)


# ===========================================================================
# PRESCRIPTIONS
# ===========================================================================
@app.route(PREFIX + "/prescriptions", methods=["POST"])
def create_prescription():
    authorize({"DispensingPharmacist", "CompoundingPharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    mfr_id = V.require_str(body, "master_formulation_record_id")
    patient_name = V.require_str(body, "patient_name")
    prescriber_npi = V.require_str(body, "prescriber_npi")
    units_prescribed = V.require_int(body, "units_prescribed")
    if units_prescribed < 1:
        raise ApiError("ERR_INVALID_REQUEST", "units_prescribed must be >= 1")
    written_utc = V.require_str(body, "written_utc")
    written_dt = timeutil.parse_iso(written_utc)

    with db.lock:
        if facility_id not in db.facilities:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")
        mfr = db.master_formulation_records.get(mfr_id)
        if mfr is None or mfr["facility_id"] != facility_id:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "master_formulation_record_id not found in facility")

        rec = store.init_common({
            "facility_id": facility_id,
            "master_formulation_record_id": mfr_id,
            "patient_name": patient_name,
            "prescriber_npi": prescriber_npi,
            "units_prescribed": units_prescribed,
            "units_dispensed": 0,
            "written_utc": timeutil.format_iso(written_dt),
            "status": "ACTIVE",
        })
        db.prescriptions[rec["id"]] = rec
        return success(store.serialize_prescription(rec), status=201)


@app.route(PREFIX + "/prescriptions", methods=["GET"])
def list_prescriptions():
    authorize(ALL_ROLES)
    records = list(db.prescriptions.values())
    fid = request.args.get("facility_id")
    mfr_id = request.args.get("master_formulation_record_id")
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    if mfr_id:
        records = [r for r in records if r["master_formulation_record_id"] == mfr_id]
    with db.lock:
        for r in records:
            store.refresh_prescription_expiry(r)
    return list_response(records, store.serialize_prescription)


@app.route(PREFIX + "/prescriptions/<pid>", methods=["GET"])
def get_prescription(pid):
    authorize(ALL_ROLES)
    p = get_prescription_or_404(pid)
    with db.lock:
        store.refresh_prescription_expiry(p)
        return success(store.serialize_prescription(p), status=200)


@app.route(PREFIX + "/prescriptions/<pid>/cancel", methods=["POST"])
def cancel_prescription(pid):
    authorize({"DispensingPharmacist"})
    p = get_prescription_or_404(pid)
    with db.lock:
        store.refresh_prescription_expiry(p)
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", "Prescription is not ACTIVE")
        if p["units_dispensed"] > 0:
            raise ApiError("ERR_PRESCRIPTION_HAS_DISPENSES", "Prescription has dispensed units")
        p["status"] = "CANCELLED"
        store.touch(p)
        return success(store.serialize_prescription(p), status=200)


# ===========================================================================
# COMPOUNDING BATCHES
# ===========================================================================
@app.route(PREFIX + "/compounding-batches", methods=["POST"])
def create_batch():
    authorize({"CompoundingPharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    mfr_id = V.require_str(body, "master_formulation_record_id")
    purpose = V.require_enum(body, "purpose", {"PRESCRIPTION", "OFFICE_USE"})
    prescription_id = V.optional_str(body, "prescription_id", None)

    with db.lock:
        facility = db.facilities.get(facility_id)
        if facility is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")
        mfr = db.master_formulation_records.get(mfr_id)
        if mfr is None or mfr["facility_id"] != facility_id:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "master_formulation_record_id not found in facility")
        if prescription_id is not None:
            presc = db.prescriptions.get(prescription_id)
            if presc is None or presc["facility_id"] != facility_id:
                raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "prescription_id not found in facility")

        # Purpose/prescription coherence (priority 10, 422).
        if purpose == "PRESCRIPTION":
            if prescription_id is None:
                raise ApiError("ERR_PURPOSE_PRESCRIPTION_MISMATCH", "PRESCRIPTION batch requires a prescription_id")
            presc = db.prescriptions.get(prescription_id)
            if presc["master_formulation_record_id"] != mfr_id:
                raise ApiError("ERR_PURPOSE_PRESCRIPTION_MISMATCH", "prescription does not belong to this formula")
        else:  # OFFICE_USE
            if prescription_id is not None:
                raise ApiError("ERR_PURPOSE_PRESCRIPTION_MISMATCH", "OFFICE_USE batch forbids a prescription_id")
            if facility["registration_type"] != "503B":
                raise ApiError("ERR_PURPOSE_PRESCRIPTION_MISMATCH", "OFFICE_USE is permitted only at a 503B facility")

        rec = store.init_common({
            "facility_id": facility_id,
            "master_formulation_record_id": mfr_id,
            "purpose": purpose,
            "prescription_id": prescription_id,
            "compiled_by_user_id": None,
            "released_by_user_id": None,
            "theoretical_yield_units": mfr["theoretical_yield_units"],
            "actual_yield_units": None,
            "yield_variance_pct": None,
            "released_at_utc": None,
            "assigned_bud_utc": None,
            "status": "DRAFT",
        })
        db.compounding_batches[rec["id"]] = rec
        return success(store.serialize_batch(rec), status=201)


@app.route(PREFIX + "/compounding-batches", methods=["GET"])
def list_batches():
    authorize(ALL_ROLES)
    records = list(db.compounding_batches.values())
    fid = request.args.get("facility_id")
    mfr_id = request.args.get("master_formulation_record_id")
    presc_id = request.args.get("prescription_id")
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    if mfr_id:
        records = [r for r in records if r["master_formulation_record_id"] == mfr_id]
    if presc_id:
        records = [r for r in records if r.get("prescription_id") == presc_id]
    return list_response(records, store.serialize_batch)


@app.route(PREFIX + "/compounding-batches/<bid>", methods=["GET"])
def get_batch(bid):
    authorize(ALL_ROLES)
    b = get_batch_or_404(bid)
    return success(store.serialize_batch(b), status=200)


def _batch_usages(bid):
    return [u for u in db.batch_ingredient_usages.values() if u["compounding_batch_id"] == bid]


def _batch_finished(bid):
    return [fp for fp in db.finished_preparations.values() if fp["compounding_batch_id"] == bid]


@app.route(PREFIX + "/compounding-batches/<bid>/start", methods=["POST"])
def start_batch(bid):
    authorize({"CompoundingPharmacist"})
    b = get_batch_or_404(bid)
    with db.lock:
        if b["status"] != "DRAFT":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not DRAFT")
        mfr = db.master_formulation_records[b["master_formulation_record_id"]]
        if mfr["status"] != "ACTIVE":
            raise ApiError("ERR_MFR_RETIRED", "Master formulation record is RETIRED")
        usages = _batch_usages(bid)
        if not usages:
            raise ApiError("ERR_NO_INGREDIENTS_CHARGED", "No ingredient usage rows charged to the batch")

        facility = db.facilities[b["facility_id"]]
        current = store.facility_clock(facility)

        # Every charged lot must be AVAILABLE and not expired.
        for u in usages:
            lot = db.ingredient_lots[u["ingredient_lot_id"]]
            store.refresh_lot_expiry(lot)
            expiry = timeutil.parse_iso(lot["expiration_utc"])
            if lot["status"] != "AVAILABLE" or not (expiry > current):
                raise ApiError("ERR_LOT_NOT_AVAILABLE", "A charged lot is not AVAILABLE or is expired")
        # Every charged lot's remaining_grams must cover grams_used.
        for u in usages:
            lot = db.ingredient_lots[u["ingredient_lot_id"]]
            store.recompute_remaining_grams(lot)
            if lot["remaining_grams"] < u["grams_used"]:
                raise ApiError("ERR_LOT_INSUFFICIENT_GRAMS", "A charged lot has insufficient remaining grams")

        # Commit: status DRAFT->IN_PROCESS, decrement remaining_grams.
        # Record the facility clock at start; anchors the environmental window.
        b["status"] = "IN_PROCESS"
        b["started_at_clock"] = facility["current_utc"]
        store.touch(b)
        for u in usages:
            lot = db.ingredient_lots[u["ingredient_lot_id"]]
            store.recompute_remaining_grams(lot)
            store.touch(lot)
        return success(store.serialize_batch(b), status=200)


@app.route(PREFIX + "/compounding-batches/<bid>/compile", methods=["POST"])
def compile_batch(bid):
    user_id, _ = authorize({"CompoundingPharmacist"})
    b = get_batch_or_404(bid)
    body = V.get_json_body()
    actual_yield = V.require_int(body, "actual_yield_units")
    if actual_yield < 0:
        raise ApiError("ERR_INVALID_REQUEST", "actual_yield_units must be >= 0")

    with db.lock:
        if b["status"] != "IN_PROCESS":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not IN_PROCESS")

        theoretical = b["theoretical_yield_units"]
        variance = calc.yield_variance_pct(actual_yield, theoretical)
        if not calc.yield_within_tolerance(variance):
            raise ApiError("ERR_YIELD_OUT_OF_RANGE", "Yield variance out of tolerance band")

        mfr = db.master_formulation_records[b["master_formulation_record_id"]]
        facility = db.facilities[b["facility_id"]]
        current = store.facility_clock(facility)

        base_days = calc.base_bud_days(mfr["is_sterile"], mfr["dosage_form"], mfr["default_bud_days_nonsterile"])
        usages = _batch_usages(bid)
        earliest_expiry = None
        for u in usages:
            lot = db.ingredient_lots[u["ingredient_lot_id"]]
            exp = timeutil.parse_iso(lot["expiration_utc"])
            if earliest_expiry is None or exp < earliest_expiry:
                earliest_expiry = exp
        bud_dt = calc.assigned_bud_utc(current, b["purpose"], base_days, earliest_expiry)
        bud_iso = timeutil.format_iso(bud_dt)

        # Commit compile.
        b["compiled_by_user_id"] = user_id
        b["actual_yield_units"] = actual_yield
        b["yield_variance_pct"] = variance
        b["assigned_bud_utc"] = bud_iso
        b["status"] = "COMPILED"
        store.touch(b)

        # Mint finished preparations.
        prefix = b["id"][0:8].upper()
        bud_date = bud_iso[0:10]  # YYYY-MM-DD
        header = "%s | LOT %s | BUD %s" % (mfr["name"], prefix, bud_date)
        if b["purpose"] == "OFFICE_USE":
            label = header + " | 503B OUTSOURCING FACILITY — OFFICE USE ONLY — NOT FOR RESALE"
        else:
            presc = db.prescriptions[b["prescription_id"]]
            label = (header + " | RX PATIENT: " + presc["patient_name"]
                     + " | PRESCRIBER NPI: " + presc["prescriber_npi"])

        for i in range(1, actual_yield + 1):
            serial = "%s-%04d" % (prefix, i)
            fp = store.init_common({
                "compounding_batch_id": b["id"],
                "facility_id": b["facility_id"],
                "unit_serial": serial,
                "label_text": label,
                "beyond_use_utc": bud_iso,
                "qc_status": "AWAITING_QC",
                "dispense_status": "IN_INVENTORY",
            })
            db.finished_preparations[fp["id"]] = fp

        return success(store.serialize_batch(b), status=200)


@app.route(PREFIX + "/compounding-batches/<bid>/quarantine", methods=["POST"])
def quarantine_batch(bid):
    authorize({"CompoundingPharmacist"})
    b = get_batch_or_404(bid)
    with db.lock:
        if b["status"] != "COMPILED":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not COMPILED")
        b["status"] = "QUARANTINED"
        store.touch(b)
        return success(store.serialize_batch(b), status=200)


@app.route(PREFIX + "/compounding-batches/<bid>/reprocess", methods=["POST"])
def reprocess_batch(bid):
    authorize({"CompoundingPharmacist"})
    b = get_batch_or_404(bid)
    with db.lock:
        if b["status"] != "QUARANTINED":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not QUARANTINED")
        finished = _batch_finished(bid)
        if any(fp["dispense_status"] == "DISPENSED" for fp in finished):
            raise ApiError("ERR_BATCH_HAS_DISPENSED_UNITS", "Batch has dispensed units")
        # Void finished preparations.
        for fp in finished:
            del db.finished_preparations[fp["id"]]
        b["compiled_by_user_id"] = None
        b["actual_yield_units"] = None
        b["yield_variance_pct"] = None
        b["assigned_bud_utc"] = None
        b["status"] = "IN_PROCESS"
        store.touch(b)
        return success(store.serialize_batch(b), status=200)


@app.route(PREFIX + "/compounding-batches/<bid>/release", methods=["POST"])
def release_batch(bid):
    user_id, _ = authorize({"QualityAssurancePharmacist"})
    b = get_batch_or_404(bid)
    body = V.get_json_body()
    expected_version = V.require_int(body, "expected_batch_version")

    with db.lock:
        # 1. State precondition.
        if b["status"] != "QUARANTINED":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not QUARANTINED")
        # 2. OCC.
        if expected_version != b["version"]:
            raise ApiError("ERR_STALE_VERSION", "Stale batch version")
        # 3. Segregation of duties.
        if user_id == b.get("compiled_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Releaser must differ from compiler")

        mfr = db.master_formulation_records[b["master_formulation_record_id"]]
        # 4. QC gate.
        required = {"POTENCY_ASSAY", "VISUAL_INSPECTION"}
        if mfr["is_sterile"]:
            required |= {"STERILITY", "ENDOTOXIN"}
        tests = [t for t in db.quality_control_tests.values() if t["compounding_batch_id"] == bid]
        by_type = {}
        for t in tests:
            by_type.setdefault(t["test_type"], []).append(t)
        # Any required test FAILED -> ERR_QC_FAILED.
        for tt in required:
            if any(t["result"] == "FAILED" for t in by_type.get(tt, [])):
                raise ApiError("ERR_QC_FAILED", "A required QC test FAILED")
        # Every required test exists and PASSED.
        for tt in required:
            if not any(t["result"] == "PASSED" for t in by_type.get(tt, [])):
                raise ApiError("ERR_QC_INCOMPLETE", "A required QC test is missing or not PASSED")

        # 5. Environmental gate (sterile only). Window = [batch start, now] on
        # the facility clock, measured via each reading's reading_utc.
        if mfr["is_sterile"]:
            facility = db.facilities[b["facility_id"]]
            now_dt = store.facility_clock(facility)
            start_marker = b.get("started_at_clock")
            start_dt = timeutil.parse_iso(start_marker) if start_marker else None
            for e in db.environmental_logs.values():
                if e["facility_id"] != b["facility_id"]:
                    continue
                if e["usp_chapter"] != "USP_797" or e["in_spec"]:
                    continue
                reading_dt = timeutil.parse_iso(e["reading_utc"])
                if reading_dt > now_dt:
                    continue
                if start_dt is None or start_dt <= reading_dt:
                    raise ApiError("ERR_ENVIRONMENTAL_EXCURSION", "Out-of-spec USP_797 reading in batch window")

        # 6. Anticipatory gate (OFFICE_USE only).
        if b["purpose"] == "OFFICE_USE":
            ledger = store.ledger_for_mfr(mfr["id"])
            store.recompute_ledger(ledger)
            if ledger["remaining_units"] < (b.get("actual_yield_units") or 0):
                raise ApiError("ERR_ANTICIPATORY_LIMIT_EXCEEDED", "Anticipatory limit exceeded")

        # Commit release.
        facility = db.facilities[b["facility_id"]]
        b["released_by_user_id"] = user_id
        b["released_at_utc"] = facility["current_utc"]
        b["status"] = "RELEASED"
        store.touch(b)  # increments version by 1
        for fp in _batch_finished(bid):
            if fp["qc_status"] == "AWAITING_QC":
                fp["qc_status"] = "QC_RELEASED"
                store.touch(fp)
        if b["purpose"] == "OFFICE_USE":
            ledger = store.ledger_for_mfr(mfr["id"])
            store.recompute_ledger(ledger)
            store.touch(ledger)
        return success(store.serialize_batch(b), status=200)


@app.route(PREFIX + "/compounding-batches/<bid>/reject", methods=["POST"])
def reject_batch(bid):
    authorize({"QualityAssurancePharmacist"})
    b = get_batch_or_404(bid)
    with db.lock:
        if b["status"] not in ("QUARANTINED", "COMPILED"):
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not QUARANTINED or COMPILED")
        b["status"] = "REJECTED"
        store.touch(b)
        for fp in _batch_finished(bid):
            fp["qc_status"] = "QC_REJECTED"
            store.touch(fp)
        # Compensating restock: now that batch is REJECTED, remaining_grams
        # recomputes to exclude this batch's usages, restoring inventory.
        for u in _batch_usages(bid):
            lot = db.ingredient_lots[u["ingredient_lot_id"]]
            store.recompute_remaining_grams(lot)
            store.touch(lot)
        return success(store.serialize_batch(b), status=200)


# ===========================================================================
# BATCH INGREDIENT USAGES
# ===========================================================================
@app.route(PREFIX + "/batch-ingredient-usages", methods=["POST"])
def create_usage():
    authorize({"CompoundingPharmacist"})
    body = V.get_json_body()
    batch_id = V.require_str(body, "compounding_batch_id")
    lot_id = V.require_str(body, "ingredient_lot_id")
    grams_used = V.require_number(body, "grams_used")
    if grams_used <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "grams_used must be > 0")

    with db.lock:
        batch = db.compounding_batches.get(batch_id)
        if batch is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "compounding_batch_id not found")
        lot = db.ingredient_lots.get(lot_id)
        if lot is None or lot["facility_id"] != batch["facility_id"]:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "ingredient_lot_id not found in facility")

        if batch["status"] != "DRAFT":
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not DRAFT")

        adjusted = calc.potency_adjusted_grams(grams_used, lot["labeled_potency_pct"])
        rec = store.init_common({
            "compounding_batch_id": batch_id,
            "ingredient_lot_id": lot_id,
            "grams_used": grams_used,
            "potency_adjusted_grams": adjusted,
        })
        db.batch_ingredient_usages[rec["id"]] = rec
        return success(store.serialize_usage(rec), status=201)


@app.route(PREFIX + "/batch-ingredient-usages", methods=["GET"])
def list_usages():
    authorize(ALL_ROLES)
    records = list(db.batch_ingredient_usages.values())
    batch_id = request.args.get("compounding_batch_id")
    lot_id = request.args.get("ingredient_lot_id")
    if batch_id:
        records = [r for r in records if r["compounding_batch_id"] == batch_id]
    if lot_id:
        records = [r for r in records if r["ingredient_lot_id"] == lot_id]
    return list_response(records, store.serialize_usage)


@app.route(PREFIX + "/batch-ingredient-usages/<uid>", methods=["GET"])
def get_usage(uid):
    authorize(ALL_ROLES)
    u = get_usage_or_404(uid)
    return success(store.serialize_usage(u), status=200)


# ===========================================================================
# QC TESTS
# ===========================================================================
@app.route(PREFIX + "/qc-tests", methods=["POST"])
def create_qc():
    authorize({"QualityAssurancePharmacist"})
    body = V.get_json_body()
    batch_id = V.require_str(body, "compounding_batch_id")
    test_type = V.require_enum(body, "test_type", {
        "POTENCY_ASSAY", "STERILITY", "ENDOTOXIN", "VISUAL_INSPECTION",
    })
    measured_value = V.optional_number(body, "measured_value", None)
    lower_limit = V.optional_number(body, "lower_limit", None)
    upper_limit = V.optional_number(body, "upper_limit", None)

    with db.lock:
        batch = db.compounding_batches.get(batch_id)
        if batch is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "compounding_batch_id not found")
        if batch["status"] not in ("COMPILED", "QUARANTINED"):
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Batch is not COMPILED or QUARANTINED")

        rec = store.init_common({
            "compounding_batch_id": batch_id,
            "test_type": test_type,
            "measured_value": measured_value,
            "lower_limit": lower_limit,
            "upper_limit": upper_limit,
            "result": "PENDING",
        })
        db.quality_control_tests[rec["id"]] = rec
        return success(store.serialize_qc(rec), status=201)


@app.route(PREFIX + "/qc-tests", methods=["GET"])
def list_qc():
    authorize(ALL_ROLES)
    records = list(db.quality_control_tests.values())
    batch_id = request.args.get("compounding_batch_id")
    if batch_id:
        records = [r for r in records if r["compounding_batch_id"] == batch_id]
    return list_response(records, store.serialize_qc)


@app.route(PREFIX + "/qc-tests/<qid>", methods=["GET"])
def get_qc(qid):
    authorize(ALL_ROLES)
    q = get_qc_or_404(qid)
    return success(store.serialize_qc(q), status=200)


@app.route(PREFIX + "/qc-tests/<qid>/begin", methods=["POST"])
def begin_qc(qid):
    authorize({"QualityAssurancePharmacist"})
    q = get_qc_or_404(qid)
    with db.lock:
        if q["result"] != "PENDING":
            raise ApiError("ERR_QC_NOT_IN_STATE", "QC test is not PENDING")
        batch = db.compounding_batches[q["compounding_batch_id"]]
        if batch["status"] not in ("COMPILED", "QUARANTINED"):
            raise ApiError("ERR_BATCH_NOT_IN_STATE", "Parent batch not in COMPILED or QUARANTINED")
        q["result"] = "IN_PROGRESS"
        store.touch(q)
        return success(store.serialize_qc(q), status=200)


@app.route(PREFIX + "/qc-tests/<qid>/record", methods=["POST"])
def record_qc(qid):
    authorize({"QualityAssurancePharmacist"})
    q = get_qc_or_404(qid)
    body = V.get_json_body()
    measured_value = V.optional_number(body, "measured_value", None)
    pass_flag = body.get("pass")

    with db.lock:
        if q["result"] != "IN_PROGRESS":
            raise ApiError("ERR_QC_NOT_IN_STATE", "QC test is not IN_PROGRESS")
        batch = db.compounding_batches[q["compounding_batch_id"]]
        mfr = db.master_formulation_records[batch["master_formulation_record_id"]]

        # Persist a freshly supplied measured_value if present.
        if measured_value is not None:
            q["measured_value"] = measured_value

        passed = _evaluate_qc(q, batch, mfr, pass_flag)
        q["result"] = "PASSED" if passed else "FAILED"
        store.touch(q)

        # Contamination-trace cascade on STERILITY/ENDOTOXIN FAILED for sterile batch.
        if (not passed and q["test_type"] in ("STERILITY", "ENDOTOXIN") and mfr["is_sterile"]):
            for u in _batch_usages(batch["id"]):
                lot = db.ingredient_lots[u["ingredient_lot_id"]]
                if lot["status"] == "AVAILABLE":
                    lot["status"] = "QUARANTINED"
                    store.touch(lot)
        return success(store.serialize_qc(q), status=200)


def _evaluate_qc(q, batch, mfr, pass_flag):
    """Return True if PASSED, False if FAILED."""
    test_type = q["test_type"]
    if test_type == "ENDOTOXIN":
        usages = _batch_usages(batch["id"])
        total_active_mg = 1000.0 * sum(u["potency_adjusted_grams"] for u in usages)
        limit = calc.endotoxin_limit(mfr["dosage_form"])
        measured = q.get("measured_value")
        if measured is None:
            raise ApiError("ERR_INVALID_REQUEST", "ENDOTOXIN record requires measured_value")
        projected = calc.endotoxin_projection(measured, total_active_mg, batch["theoretical_yield_units"])
        return projected <= limit

    # Numeric test (has limits + measured_value).
    measured = q.get("measured_value")
    lower = q.get("lower_limit")
    upper = q.get("upper_limit")
    if measured is not None and lower is not None and upper is not None:
        return lower <= measured <= upper

    # Pass/fail-only test.
    if isinstance(pass_flag, bool):
        return pass_flag
    raise ApiError("ERR_INVALID_REQUEST", "Recording requires measured_value with limits or a boolean pass flag")


# ===========================================================================
# FINISHED PREPARATIONS
# ===========================================================================
@app.route(PREFIX + "/finished-preparations", methods=["GET"])
def list_finished():
    authorize(ALL_ROLES)
    records = list(db.finished_preparations.values())
    batch_id = request.args.get("compounding_batch_id")
    fid = request.args.get("facility_id")
    if batch_id:
        records = [r for r in records if r["compounding_batch_id"] == batch_id]
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    return list_response(records, store.serialize_finished)


@app.route(PREFIX + "/finished-preparations/<fpid>", methods=["GET"])
def get_finished(fpid):
    authorize(ALL_ROLES)
    fp = get_finished_or_404(fpid)
    return success(store.serialize_finished(fp), status=200)


# ===========================================================================
# DISPENSES
# ===========================================================================
@app.route(PREFIX + "/dispenses", methods=["POST"])
def create_dispense():
    authorize({"DispensingPharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    fp_id = V.require_str(body, "finished_preparation_id")
    prescription_id = V.optional_str(body, "prescription_id", None)
    office_account_name = V.optional_str(body, "office_account_name", None)

    with db.lock:
        facility = db.facilities.get(facility_id)
        if facility is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")
        fp = db.finished_preparations.get(fp_id)
        if fp is None or fp["facility_id"] != facility_id:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "finished_preparation_id not found in facility")
        if prescription_id is not None:
            presc = db.prescriptions.get(prescription_id)
            if presc is None or presc["facility_id"] != facility_id:
                raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "prescription_id not found in facility")

        batch = db.compounding_batches[fp["compounding_batch_id"]]

        # Channel coherence (priority 14, 422).
        if batch["purpose"] == "PRESCRIPTION":
            if prescription_id is None or office_account_name is not None:
                raise ApiError("ERR_DISPENSE_CHANNEL_MISMATCH", "PRESCRIPTION unit requires prescription_id, forbids office_account_name")
            presc = db.prescriptions.get(prescription_id)
            store.refresh_prescription_expiry(presc)
            if presc["status"] != "ACTIVE":
                raise ApiError("ERR_DISPENSE_CHANNEL_MISMATCH", "Prescription is not ACTIVE")
            if presc["master_formulation_record_id"] != batch["master_formulation_record_id"]:
                raise ApiError("ERR_DISPENSE_CHANNEL_MISMATCH", "Prescription formula does not match the unit's batch")
        else:  # OFFICE_USE
            if office_account_name is None or prescription_id is not None:
                raise ApiError("ERR_DISPENSE_CHANNEL_MISMATCH", "OFFICE_USE unit requires office_account_name, forbids prescription_id")

        # Unit-state preconditions.
        if fp["qc_status"] != "QC_RELEASED":
            raise ApiError("ERR_UNIT_NOT_RELEASED", "Unit is not QC_RELEASED")
        if fp["dispense_status"] != "IN_INVENTORY":
            raise ApiError("ERR_UNIT_NOT_IN_INVENTORY", "Unit is not IN_INVENTORY")
        current = store.facility_clock(facility)
        bud = timeutil.parse_iso(fp["beyond_use_utc"])
        if current > bud:
            raise ApiError("ERR_BEYOND_USE_DATE_PASSED", "Beyond-use date has passed")

        # Commit dispense.
        fp["dispense_status"] = "DISPENSED"
        store.touch(fp)
        rec = store.init_common({
            "facility_id": facility_id,
            "finished_preparation_id": fp_id,
            "prescription_id": prescription_id,
            "office_account_name": office_account_name,
            "dispensed_utc": facility["current_utc"],
        })
        db.dispenses[rec["id"]] = rec

        if batch["purpose"] == "PRESCRIPTION":
            presc = db.prescriptions[prescription_id]
            presc["units_dispensed"] += 1
            if presc["units_dispensed"] == presc["units_prescribed"] and presc["status"] == "ACTIVE":
                presc["status"] = "FILLED"
            store.touch(presc)

        return success(store.serialize_dispense(rec), status=201)


@app.route(PREFIX + "/dispenses", methods=["GET"])
def list_dispenses():
    authorize(ALL_ROLES)
    records = list(db.dispenses.values())
    fp_id = request.args.get("finished_preparation_id")
    presc_id = request.args.get("prescription_id")
    fid = request.args.get("facility_id")
    if fp_id:
        records = [r for r in records if r["finished_preparation_id"] == fp_id]
    if presc_id:
        records = [r for r in records if r.get("prescription_id") == presc_id]
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    return list_response(records, store.serialize_dispense)


@app.route(PREFIX + "/dispenses/<did>", methods=["GET"])
def get_dispense(did):
    authorize(ALL_ROLES)
    d = get_dispense_or_404(did)
    return success(store.serialize_dispense(d), status=200)


# ===========================================================================
# RECALLS
# ===========================================================================
@app.route(PREFIX + "/recalls", methods=["POST"])
def create_recall():
    authorize({"QualityAssurancePharmacist"})
    body = V.get_json_body()
    facility_id = V.require_str(body, "facility_id")
    batch_id = V.require_str(body, "compounding_batch_id")
    reason = V.require_enum(body, "reason", {
        "STERILITY_FAILURE", "POTENCY_OOS", "ENDOTOXIN_OOS", "ENVIRONMENTAL_EXCURSION", "LABELING_ERROR",
    })
    classification = V.require_enum(body, "classification", {"CLASS_I", "CLASS_II", "CLASS_III"})

    with db.lock:
        if facility_id not in db.facilities:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "facility_id does not reference an existing facility")
        batch = db.compounding_batches.get(batch_id)
        if batch is None or batch["facility_id"] != facility_id:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "compounding_batch_id not found in facility")

        if batch["status"] != "RELEASED":
            raise ApiError("ERR_BATCH_NOT_RELEASED", "Batch is not RELEASED")

        finished = _batch_finished(batch_id)
        units_in_scope = len(finished)

        # Create recall.
        rec = store.init_common({
            "facility_id": facility_id,
            "compounding_batch_id": batch_id,
            "reason": reason,
            "classification": classification,
            "units_in_scope": units_in_scope,
            "units_reconciled": 0,
            "status": "INITIATED",
        })
        db.recalls[rec["id"]] = rec

        # Cascade: batch RELEASED -> RECALLED.
        batch["status"] = "RECALLED"
        store.touch(batch)
        # Every finished preparation -> RECALLED, reverting prescriptions for dispensed units.
        for fp in finished:
            was_dispensed = fp["dispense_status"] == "DISPENSED"
            fp["dispense_status"] = "RECALLED"
            store.touch(fp)
            if was_dispensed and batch["purpose"] == "PRESCRIPTION":
                presc = db.prescriptions.get(batch.get("prescription_id"))
                if presc is not None:
                    presc["units_dispensed"] = max(0, presc["units_dispensed"] - 1)
                    if presc["status"] == "FILLED":
                        presc["status"] = "ACTIVE"
                    store.touch(presc)
        # OFFICE_USE: recompute anticipatory ledger (recalled batch leaves the window).
        if batch["purpose"] == "OFFICE_USE":
            ledger = store.ledger_for_mfr(batch["master_formulation_record_id"])
            if ledger is not None:
                store.recompute_ledger(ledger)
                store.touch(ledger)

        return success(store.serialize_recall(rec), status=201)


@app.route(PREFIX + "/recalls", methods=["GET"])
def list_recalls():
    authorize(ALL_ROLES)
    records = list(db.recalls.values())
    fid = request.args.get("facility_id")
    batch_id = request.args.get("compounding_batch_id")
    if fid:
        records = [r for r in records if r["facility_id"] == fid]
    if batch_id:
        records = [r for r in records if r["compounding_batch_id"] == batch_id]
    return list_response(records, store.serialize_recall)


@app.route(PREFIX + "/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    authorize(ALL_ROLES)
    r = get_recall_or_404(rid)
    return success(store.serialize_recall(r), status=200)


@app.route(PREFIX + "/recalls/<rid>/advance", methods=["POST"])
def advance_recall(rid):
    authorize({"QualityAssurancePharmacist"})
    r = get_recall_or_404(rid)
    with db.lock:
        if r["status"] != "INITIATED":
            raise ApiError("ERR_RECALL_NOT_IN_STATE", "Recall is not INITIATED")
        r["status"] = "IN_PROGRESS"
        store.touch(r)
        return success(store.serialize_recall(r), status=200)


@app.route(PREFIX + "/recalls/<rid>/reconcile", methods=["POST"])
def reconcile_recall(rid):
    authorize({"QualityAssurancePharmacist"})
    r = get_recall_or_404(rid)
    with db.lock:
        if r["status"] != "IN_PROGRESS":
            raise ApiError("ERR_RECALL_NOT_IN_STATE", "Recall is not IN_PROGRESS")
        # Recompute units_reconciled = in-scope units now in RECALLED dispense status.
        finished = _batch_finished(r["compounding_batch_id"])
        reconciled = sum(1 for fp in finished if fp["dispense_status"] == "RECALLED")
        r["units_reconciled"] = reconciled
        if reconciled != r["units_in_scope"]:
            store.touch(r)
            raise ApiError("ERR_RECALL_UNITS_OUTSTANDING", "Units still outstanding")
        r["status"] = "RECONCILED"
        store.touch(r)
        return success(store.serialize_recall(r), status=200)


@app.route(PREFIX + "/recalls/<rid>/reopen", methods=["POST"])
def reopen_recall(rid):
    authorize({"QualityAssurancePharmacist"})
    r = get_recall_or_404(rid)
    with db.lock:
        if r["status"] != "IN_PROGRESS":
            raise ApiError("ERR_RECALL_NOT_IN_STATE", "Recall is not IN_PROGRESS")
        r["status"] = "INITIATED"
        store.touch(r)
        return success(store.serialize_recall(r), status=200)


@app.route(PREFIX + "/recalls/<rid>/close", methods=["POST"])
def close_recall(rid):
    authorize({"QualityAssurancePharmacist"})
    r = get_recall_or_404(rid)
    with db.lock:
        if r["status"] != "RECONCILED":
            raise ApiError("ERR_RECALL_NOT_IN_STATE", "Recall is not RECONCILED")
        r["status"] = "CLOSED"
        store.touch(r)
        return success(store.serialize_recall(r), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
