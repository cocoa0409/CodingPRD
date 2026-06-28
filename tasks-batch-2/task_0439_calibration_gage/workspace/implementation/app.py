"""Calibration & Gage Management API — Flask entry point.

In-memory only. No seeding. Server boots with current_epoch == 0.
Every behavior traces to PRD.md.
"""
import os

from flask import Flask, request

import calculations as calc
import serializers as ser
from db import db, common_fields, touch, new_id
from errors import ApiError, err
from middleware import require_auth, get_json, get_pagination
from response import success, success_list, error_response
import validators as val

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 422, str(e))


# ---------------------------------------------------------------------------
# List helper — sort by created_at ASC (PRD §2.3), paginate.
# ---------------------------------------------------------------------------
def paginate(rows, serialize):
    limit, offset = get_pagination()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers (ERR_NOT_FOUND, left-to-right path validation).
# ---------------------------------------------------------------------------
def get_or_404(store, _id):
    row = store.get(_id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found" % _id)
    return row


# ===========================================================================
# Logical Clock
# ===========================================================================
@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_auth(["QualityEngineer"])
    body = get_json()
    by_epochs = val.require_int(body, "by_epochs")
    db.clock["current_epoch"] += by_epochs
    # Recall sweep — PRD §3.8: every ACTIVE instrument with
    # calibration_status==IN_TOLERANCE and next_due_epoch non-null and
    # strictly < current_epoch -> OVERDUE, version bump.
    current = db.clock["current_epoch"]
    for inst in db.instruments.values():
        if (inst["lifecycle_status"] == "ACTIVE"
                and inst["calibration_status"] == "IN_TOLERANCE"
                and inst.get("next_due_epoch") is not None
                and inst["next_due_epoch"] < current):
            inst["calibration_status"] = "OVERDUE"
            touch(inst)
    return success(ser.serialize_clock(), 200)


@app.route("/_clock", methods=["GET"])
def clock_read():
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    return success(ser.serialize_clock(), 200)


# ===========================================================================
# Calibration Standards (self-referential DAG)
# ===========================================================================
def _validate_traceability(standard_id, parent_id):
    """Walk parent links; reject cycle/self-ref/over-depth.

    ERR_TRACEABILITY_CYCLE (409). Called after FK existence is confirmed.
    standard_id may be None at create (no node yet).
    """
    if parent_id is None:
        return
    if standard_id is not None and parent_id == standard_id:
        raise err("ERR_TRACEABILITY_CYCLE", "A standard cannot be its own parent")
    # Walk up from parent; if we ever reach standard_id -> cycle.
    depth = 1  # link from new node to parent counts as depth 1
    seen = set()
    cur_id = parent_id
    while cur_id is not None:
        if standard_id is not None and cur_id == standard_id:
            raise err("ERR_TRACEABILITY_CYCLE",
                      "parent_standard_id chain forms a cycle")
        if cur_id in seen:
            raise err("ERR_TRACEABILITY_CYCLE",
                      "parent_standard_id chain forms a cycle")
        seen.add(cur_id)
        node = db.calibration_standards.get(cur_id)
        if node is None:
            break
        next_parent = node.get("parent_standard_id")
        if next_parent is None:
            break
        depth += 1
        if depth > calc.MAX_DEPTH:
            raise err("ERR_TRACEABILITY_CYCLE",
                      "parent_standard_id chain exceeds max depth")
        cur_id = next_parent


@app.route("/calibration-standards", methods=["POST"])
def create_standard():
    require_auth(["Metrologist"])
    body = get_json()
    # FK existence (parent_standard_id) — priority 4 before request validity is
    # acceptable here, but PRD §2.10 orders FK existence (404) before request
    # validity (422). We check FK presence/existence first.
    parent_id = None
    if "parent_standard_id" in body and body.get("parent_standard_id") is not None:
        parent_id = body.get("parent_standard_id")
        if not isinstance(parent_id, str) or parent_id not in db.calibration_standards:
            raise err("ERR_FK_NOT_FOUND", "parent_standard_id does not exist")

    # Request validity (422)
    name = val.require_string(body, "name")
    nist_test_number = val.require_string_allow_empty(body, "nist_test_number")
    nominal_value = val.require_number(body, "nominal_value")
    standard_unit = val.require_string(body, "standard_unit")
    uncertainty = val.require_nonneg_number(body, "uncertainty")
    certified_through_epoch = val.require_int(body, "certified_through_epoch")
    # nist_test_number '' permitted only when parent_standard_id set (PRD §2.8)
    if nist_test_number == "" and parent_id is None:
        raise err("ERR_INVALID_REQUEST",
                  "nist_test_number is required when parent_standard_id is null")

    # Traceability cycle (409)
    _validate_traceability(None, parent_id)

    row = common_fields()
    row.update({
        "name": name,
        "nist_test_number": nist_test_number,
        "parent_standard_id": parent_id,
        "nominal_value": nominal_value,
        "standard_unit": standard_unit,
        "uncertainty": uncertainty,
        "certified_through_epoch": certified_through_epoch,
        "status": "ACTIVE",
    })
    db.calibration_standards[row["id"]] = row
    return success(ser.serialize_standard(row), 201)


@app.route("/calibration-standards", methods=["GET"])
def list_standards():
    require_auth(["Metrologist", "Technician", "QualityEngineer"])
    parent_filter = request.args.get("parent_standard_id")
    rows = list(db.calibration_standards.values())
    if parent_filter is not None:
        rows = [r for r in rows if r.get("parent_standard_id") == parent_filter]
    return paginate(rows, ser.serialize_standard)


@app.route("/calibration-standards/<sid>", methods=["GET"])
def get_standard(sid):
    require_auth(["Metrologist", "Technician", "QualityEngineer"])
    row = get_or_404(db.calibration_standards, sid)
    return success(ser.serialize_standard(row), 200)


@app.route("/calibration-standards/<sid>", methods=["PUT"])
def update_standard(sid):
    require_auth(["Metrologist"])
    row = get_or_404(db.calibration_standards, sid)
    body = get_json()

    # FK existence for parent_standard_id if provided (404)
    new_parent = row.get("parent_standard_id")
    if "parent_standard_id" in body:
        pv = body.get("parent_standard_id")
        if pv is None:
            new_parent = None
        else:
            if not isinstance(pv, str) or pv not in db.calibration_standards:
                raise err("ERR_FK_NOT_FOUND", "parent_standard_id does not exist")
            new_parent = pv

    # Request validity (422)
    if "certified_through_epoch" in body and body.get("certified_through_epoch") is not None:
        val.require_int(body, "certified_through_epoch")
    if "uncertainty" in body and body.get("uncertainty") is not None:
        val.require_nonneg_number(body, "uncertainty")
    new_status = row["status"]
    if "status" in body and body.get("status") is not None:
        new_status = val.require_enum(body, "status", {"ACTIVE", "RETIRED"})

    # Traceability re-validation (409)
    _validate_traceability(sid, new_parent)

    row["parent_standard_id"] = new_parent
    if "certified_through_epoch" in body and body.get("certified_through_epoch") is not None:
        row["certified_through_epoch"] = body["certified_through_epoch"]
    if "uncertainty" in body and body.get("uncertainty") is not None:
        row["uncertainty"] = body["uncertainty"]
    row["status"] = new_status
    touch(row)
    return success(ser.serialize_standard(row), 200)


# ===========================================================================
# Calibration Vendors
# ===========================================================================
@app.route("/calibration-vendors", methods=["POST"])
def create_vendor():
    require_auth(["Metrologist"])
    body = get_json()
    name = val.require_string(body, "name")
    accreditation_body = val.require_enum(
        body, "accreditation_body", {"A2LA", "NVLAP", "UKAS", "NONE"})
    accredited_through_epoch = val.require_int(body, "accredited_through_epoch")
    accreditation_number = None
    if "accreditation_number" in body and body.get("accreditation_number") is not None:
        accreditation_number = val.require_string_allow_empty(body, "accreditation_number")
    # required (non-empty) unless body == NONE (PRD §2.9)
    if accreditation_body != "NONE":
        if not accreditation_number:
            raise err("ERR_INVALID_REQUEST",
                      "accreditation_number is required unless accreditation_body is NONE")

    row = common_fields()
    row.update({
        "name": name,
        "accreditation_body": accreditation_body,
        "accreditation_number": accreditation_number,
        "accredited_through_epoch": accredited_through_epoch,
        "status": "ACTIVE",
    })
    db.calibration_vendors[row["id"]] = row
    return success(ser.serialize_vendor(row), 201)


@app.route("/calibration-vendors", methods=["GET"])
def list_vendors():
    require_auth(["Metrologist", "Technician", "QualityEngineer"])
    return paginate(list(db.calibration_vendors.values()), ser.serialize_vendor)


@app.route("/calibration-vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    require_auth(["Metrologist", "Technician", "QualityEngineer"])
    row = get_or_404(db.calibration_vendors, vid)
    return success(ser.serialize_vendor(row), 200)


@app.route("/calibration-vendors/<vid>", methods=["PATCH"])
def update_vendor(vid):
    require_auth(["Metrologist"])
    row = get_or_404(db.calibration_vendors, vid)
    body = get_json()
    if "accredited_through_epoch" in body and body.get("accredited_through_epoch") is not None:
        row["accredited_through_epoch"] = val.require_int(body, "accredited_through_epoch")
    if "status" in body and body.get("status") is not None:
        row["status"] = val.require_enum(body, "status", {"ACTIVE", "SUSPENDED"})
    touch(row)
    return success(ser.serialize_vendor(row), 200)


# ===========================================================================
# Instruments
# ===========================================================================
@app.route("/instruments", methods=["POST"])
def create_instrument():
    require_auth(["QualityEngineer"])
    body = get_json()
    asset_tag = val.require_string(body, "asset_tag")
    description = val.require_string_allow_empty(body, "description")
    nominal_value = val.require_number(body, "nominal_value")
    tolerance_plus = val.require_nonneg_number(body, "tolerance_plus")
    tolerance_minus = val.require_nonneg_number(body, "tolerance_minus")
    measurement_unit = val.require_string(body, "measurement_unit")
    calibration_interval_epochs = val.require_int(body, "calibration_interval_epochs")
    if calibration_interval_epochs < 1:
        raise err("ERR_INVALID_REQUEST", "calibration_interval_epochs must be >= 1")
    criticality = val.require_enum(body, "criticality", {"CRITICAL", "MAJOR", "MINOR"})

    # asset_tag unique among non-RETIRED instruments (409)
    for inst in db.instruments.values():
        if inst["lifecycle_status"] != "RETIRED" and inst["asset_tag"] == asset_tag:
            raise err("ERR_DUPLICATE_ASSET_TAG",
                      "asset_tag already used by a non-RETIRED instrument")

    row = common_fields()
    row.update({
        "asset_tag": asset_tag,
        "description": description,
        "nominal_value": nominal_value,
        "tolerance_plus": tolerance_plus,
        "tolerance_minus": tolerance_minus,
        "measurement_unit": measurement_unit,
        "calibration_interval_epochs": calibration_interval_epochs,
        "criticality": criticality,
        "last_calibration_epoch": None,
        "next_due_epoch": None,
        "lifecycle_status": "ACTIVE",
        "calibration_status": "UNCALIBRATED",
        "open_oot_count": 0,
    })
    db.instruments[row["id"]] = row
    return success(ser.serialize_instrument(row), 201)


@app.route("/instruments", methods=["GET"])
def list_instruments():
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    rows = list(db.instruments.values())
    lc = request.args.get("lifecycle_status")
    cs = request.args.get("calibration_status")
    if lc is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lc]
    if cs is not None:
        rows = [r for r in rows if r["calibration_status"] == cs]
    return paginate(rows, ser.serialize_instrument)


@app.route("/instruments/<iid>", methods=["GET"])
def get_instrument(iid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    row = get_or_404(db.instruments, iid)
    return success(ser.serialize_instrument(row), 200)


def _sync_open_oot_count(inst):
    inst["open_oot_count"] = ser.instrument_open_oot_count(inst)


@app.route("/instruments/<iid>/release", methods=["POST"])
def release_instrument(iid):
    require_auth(["QualityEngineer"])
    inst = get_or_404(db.instruments, iid)
    # State (409): must be QUARANTINED
    if inst["lifecycle_status"] != "QUARANTINED":
        raise err("ERR_INVALID_STATE", "Instrument is not QUARANTINED")
    # open_oot_count == 0 (409)
    _sync_open_oot_count(inst)
    if inst["open_oot_count"] != 0:
        raise err("ERR_OPEN_IMPACT_EXISTS",
                  "Instrument has open out-of-tolerance impacts")
    # latest finalized event result IN {PASS, CONDITIONAL} (409)
    latest = _latest_finalized_event(iid)
    if latest is None or latest.get("result") not in ("PASS", "CONDITIONAL"):
        raise err("ERR_LATEST_CAL_NOT_PASSING",
                  "Latest finalized calibration is not passing")
    inst["lifecycle_status"] = "ACTIVE"
    touch(inst)
    return success(ser.serialize_instrument(inst), 200)


@app.route("/instruments/<iid>/retire", methods=["POST"])
def retire_instrument(iid):
    require_auth(["QualityEngineer"])
    inst = get_or_404(db.instruments, iid)
    # from ACTIVE|QUARANTINED -> RETIRED (state)
    if inst["lifecycle_status"] not in ("ACTIVE", "QUARANTINED"):
        raise err("ERR_INVALID_STATE", "Instrument cannot be retired from its state")
    # No DRAFT/IN_PROGRESS event (409)
    for e in db.calibration_events.values():
        if e["instrument_id"] == iid and e["status"] in ("DRAFT", "IN_PROGRESS"):
            raise err("ERR_OPEN_CALIBRATION_EXISTS",
                      "Instrument has an open calibration event")
    # open_oot_count == 0 (409)
    _sync_open_oot_count(inst)
    if inst["open_oot_count"] != 0:
        raise err("ERR_OPEN_IMPACT_EXISTS",
                  "Instrument has open out-of-tolerance impacts")
    inst["lifecycle_status"] = "RETIRED"
    touch(inst)
    return success(ser.serialize_instrument(inst), 200)


@app.route("/instruments/<iid>/drift-trend", methods=["GET"])
def drift_trend(iid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    inst = get_or_404(db.instruments, iid)
    method = request.args.get("method", "LSQ")
    if method not in ("LSQ", "ENDPOINT"):
        raise err("ERR_INVALID_REQUEST", "method must be LSQ or ENDPOINT")
    # Finalized events: status reflecting PASS/CONDITIONAL/FAIL.
    finalized_statuses = {"PASSED", "CONDITIONAL_PASS", "FAILED"}
    events = [e for e in db.calibration_events.values()
              if e["instrument_id"] == iid and e["status"] in finalized_statuses]
    events.sort(key=lambda e: (e["scheduled_epoch"], e["created_at"]))
    series = [(e["scheduled_epoch"], e["max_abs_deviation"]) for e in events]
    result = calc.compute_drift_trend(
        series, method, inst["tolerance_plus"], inst["tolerance_minus"])
    return success(result, 200)


# ===========================================================================
# Calibration Events
# ===========================================================================
def _latest_finalized_event(instrument_id):
    """Latest finalized event by (scheduled_epoch, created_at) — PRD release rule.

    'latest finalized calibration event' interpreted as the most recent finalized
    event ordered by scheduled_epoch then created_at.
    """
    finalized = [e for e in db.calibration_events.values()
                 if e["instrument_id"] == instrument_id
                 and e["status"] in ("PASSED", "CONDITIONAL_PASS", "FAILED")]
    if not finalized:
        return None
    finalized.sort(key=lambda e: (e["scheduled_epoch"], e["created_at"]))
    return finalized[-1]


@app.route("/instruments/<iid>/calibration-events", methods=["POST"])
def create_event(iid):
    user_id, role = require_auth(["Technician"])
    inst = get_or_404(db.instruments, iid)
    body = get_json()

    # FK existence: standard_id (required), vendor_id (optional) — 404
    standard_id = body.get("standard_id")
    if not isinstance(standard_id, str) or standard_id == "":
        # Missing/ill-typed FK field -> treat as invalid request (422) per §2.10
        # ordering only after FK existence; but a missing FK can't be "not found".
        raise err("ERR_INVALID_REQUEST", "standard_id is required")
    if standard_id not in db.calibration_standards:
        raise err("ERR_FK_NOT_FOUND", "standard_id does not exist")
    vendor_id = None
    if "vendor_id" in body and body.get("vendor_id") is not None:
        vendor_id = body.get("vendor_id")
        if not isinstance(vendor_id, str) or vendor_id not in db.calibration_vendors:
            raise err("ERR_FK_NOT_FOUND", "vendor_id does not exist")

    # Request validity (422)
    scheduled_epoch = val.require_int(body, "scheduled_epoch")
    expected_version = val.require_int(body, "expected_instrument_version")

    # Retired instrument write guard (PRD §3.1: any write to a RETIRED
    # instrument or its children is refused).
    if inst["lifecycle_status"] == "RETIRED":
        raise err("ERR_INSTRUMENT_RETIRED", "Instrument is retired")

    # OCC (412) — expected_instrument_version must equal current version.
    if expected_version != inst["version"]:
        raise err("ERR_STALE_INSTRUMENT_VERSION",
                  "expected_instrument_version does not match current version")

    row = common_fields()
    row.update({
        "instrument_id": iid,
        "standard_id": standard_id,
        "vendor_id": vendor_id,
        "performed_by_user_id": user_id,
        "scheduled_epoch": scheduled_epoch,
        "result": None,
        "as_found_in_tolerance": None,
        "as_left_in_tolerance": None,
        "max_abs_deviation": None,
        "tur": None,
        "status": "DRAFT",
    })
    db.calibration_events[row["id"]] = row
    # Registering calibration activity bumps the instrument version (OCC guard).
    touch(inst)
    return success(ser.serialize_event(row), 201)


@app.route("/instruments/<iid>/calibration-events", methods=["GET"])
def list_instrument_events(iid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.instruments, iid)
    rows = [e for e in db.calibration_events.values() if e["instrument_id"] == iid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.serialize_event)


@app.route("/calibration-events", methods=["GET"])
def list_events():
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    rows = list(db.calibration_events.values())
    standard_id = request.args.get("standard_id")
    vendor_id = request.args.get("vendor_id")
    if standard_id is not None:
        rows = [r for r in rows if r["standard_id"] == standard_id]
    if vendor_id is not None:
        rows = [r for r in rows if r.get("vendor_id") == vendor_id]
    return paginate(rows, ser.serialize_event)


@app.route("/calibration-events/<eid>", methods=["GET"])
def get_event(eid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    row = get_or_404(db.calibration_events, eid)
    return success(ser.serialize_event(row), 200)


@app.route("/calibration-events/<eid>/start", methods=["POST"])
def start_event(eid):
    require_auth(["Technician"])
    event = get_or_404(db.calibration_events, eid)
    inst = db.instruments[event["instrument_id"]]

    # State: must be DRAFT (409)
    if event["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Event is not DRAFT")
    # Retired guard
    if inst["lifecycle_status"] == "RETIRED":
        raise err("ERR_INSTRUMENT_RETIRED", "Instrument is retired")
    # Instrument ACTIVE (409)
    if inst["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INSTRUMENT_NOT_ACTIVE", "Instrument is not ACTIVE")
    # At least one measurement point (409)
    points = [p for p in db.measurement_points.values()
              if p["calibration_event_id"] == eid]
    if not points:
        raise err("ERR_NO_MEASUREMENT_POINTS", "Event has no measurement points")
    # standard is_traceable (409)
    standard = db.calibration_standards.get(event["standard_id"])
    if standard is None or not ser.standard_is_traceable(standard):
        raise err("ERR_STANDARD_NOT_TRACEABLE", "Standard is not traceable to NIST")
    # vendor eligibility (409)
    if event.get("vendor_id"):
        vendor = db.calibration_vendors.get(event["vendor_id"])
        if (vendor is None or vendor["status"] != "ACTIVE"
                or not ser.vendor_is_accreditation_current(vendor)):
            raise err("ERR_VENDOR_NOT_ELIGIBLE", "Vendor is not eligible")

    event["status"] = "IN_PROGRESS"
    touch(event)
    return success(ser.serialize_event(event), 200)


@app.route("/calibration-events/<eid>/finalize", methods=["POST"])
def finalize_event(eid):
    require_auth(["Technician"])
    event = get_or_404(db.calibration_events, eid)
    inst = db.instruments[event["instrument_id"]]

    # State: must be IN_PROGRESS (409)
    if event["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Event is not IN_PROGRESS")

    points = [p for p in db.measurement_points.values()
              if p["calibration_event_id"] == eid]
    # start precondition guarantees >= 1 point.

    as_found_all = all(p["as_found_pass"] for p in points)
    as_left_all = all(p["as_left_pass"] for p in points)
    mad = calc.max_abs_deviation(points)
    standard = db.calibration_standards[event["standard_id"]]
    tur_value, tur_meets = calc.compute_tur(
        inst["tolerance_plus"], inst["tolerance_minus"], standard["uncertainty"])
    result = calc.compute_result(as_found_all, as_left_all, tur_meets)

    # Cascade guard (PRD §3.4) checked before mutation.
    if result in ("PASS", "CONDITIONAL"):
        if inst["lifecycle_status"] == "RETIRED":
            raise err("ERR_INSTRUMENT_RETIRED", "Instrument is retired")
    else:  # FAIL
        if inst["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INSTRUMENT_NOT_ACTIVE", "Instrument is not ACTIVE")

    # Persist event diagnostics
    event["as_found_in_tolerance"] = as_found_all
    event["as_left_in_tolerance"] = as_left_all
    event["max_abs_deviation"] = mad
    event["tur"] = tur_value
    event["result"] = result

    if result == "PASS":
        event["status"] = "PASSED"
    elif result == "CONDITIONAL":
        event["status"] = "CONDITIONAL_PASS"
    else:
        event["status"] = "FAILED"
    touch(event)

    if result in ("PASS", "CONDITIONAL"):
        inst["calibration_status"] = "IN_TOLERANCE"
        _recompute_scheduling(inst)
        touch(inst)
    else:
        # FAIL two-hop cascade
        inst["calibration_status"] = "OUT_OF_TOLERANCE"
        inst["lifecycle_status"] = "QUARANTINED"
        _auto_create_impact(inst, event)
        _sync_open_oot_count(inst)
        touch(inst)

    return success(ser.serialize_event(event), 200)


def _recompute_scheduling(inst):
    """Pinned-order scheduling recompute — calc next_due_epoch (PRD §3.4)."""
    passing = [e for e in db.calibration_events.values()
               if e["instrument_id"] == inst["id"]
               and e.get("result") in ("PASS", "CONDITIONAL")]
    last_cal = calc.compute_last_calibration_epoch(passing)
    inst["last_calibration_epoch"] = last_cal
    if last_cal is None:
        inst["next_due_epoch"] = None
    else:
        inst["next_due_epoch"] = last_cal + inst["calibration_interval_epochs"]
    # Step 3/4: overdue derivation — only when ACTIVE and currently IN_TOLERANCE.
    nde = inst["next_due_epoch"]
    is_overdue = nde is not None and nde < db.clock["current_epoch"]
    if (is_overdue and inst["lifecycle_status"] == "ACTIVE"
            and inst["calibration_status"] == "IN_TOLERANCE"):
        inst["calibration_status"] = "OVERDUE"


def _auto_create_impact(inst, event):
    """Auto-create OutOfToleranceImpact(OPEN) — calc suspect_window (PRD §3.5)."""
    trigger_epoch = event["scheduled_epoch"]
    prior_candidates = [
        e for e in db.calibration_events.values()
        if e["instrument_id"] == inst["id"]
        and e.get("result") in ("PASS", "CONDITIONAL")
        and e["scheduled_epoch"] < trigger_epoch
    ]
    prior = calc.compute_prior_calibration_epoch(prior_candidates)
    if prior is not None:
        start_epoch = prior
    else:
        # integer epoch of instrument.created_at — 0 at boot default (PRD §3.5)
        start_epoch = 0
    impact = common_fields()
    impact.update({
        "instrument_id": inst["id"],
        "triggering_event_id": event["id"],
        "prior_calibration_epoch": prior,
        "suspect_window_start_epoch": start_epoch,
        "suspect_window_end_epoch": trigger_epoch,
        "dispositioned_by_user_id": None,
        "disposition": None,
        "status": "OPEN",
    })
    db.impacts[impact["id"]] = impact
    return impact


@app.route("/calibration-events/<eid>/reopen", methods=["POST"])
def reopen_event(eid):
    require_auth(["Technician"])
    event = get_or_404(db.calibration_events, eid)
    inst = db.instruments[event["instrument_id"]]
    # State: FAILED (409)
    if event["status"] != "FAILED":
        raise err("ERR_INVALID_STATE", "Event is not FAILED")
    # The auto-created impact for this event must be CANCELLED (409)
    impact = next((i for i in db.impacts.values()
                   if i["triggering_event_id"] == eid), None)
    if impact is None or impact["status"] != "CANCELLED":
        raise err("ERR_IMPACT_NOT_CANCELLED",
                  "The impact for this event is not CANCELLED")
    # Owning instrument QUARANTINED (409)
    if inst["lifecycle_status"] != "QUARANTINED":
        raise err("ERR_INVALID_STATE", "Instrument is not QUARANTINED")
    event["status"] = "IN_PROGRESS"
    event["result"] = None
    touch(event)
    return success(ser.serialize_event(event), 200)


@app.route("/calibration-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    require_auth(["Technician"])
    event = get_or_404(db.calibration_events, eid)
    if event["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Event is not DRAFT")
    event["status"] = "CANCELLED"
    touch(event)
    return success(ser.serialize_event(event), 200)


# ===========================================================================
# Measurement Points
# ===========================================================================
@app.route("/calibration-events/<eid>/measurement-points", methods=["POST"])
def create_point(eid):
    require_auth(["Technician"])
    event = get_or_404(db.calibration_events, eid)
    inst = db.instruments[event["instrument_id"]]
    if inst["lifecycle_status"] == "RETIRED":
        raise err("ERR_INSTRUMENT_RETIRED", "Instrument is retired")
    body = get_json()
    point_label = val.require_string(body, "point_label")
    nominal = val.require_number(body, "nominal")
    tol_plus = val.require_nonneg_number(body, "tol_plus")
    tol_minus = val.require_nonneg_number(body, "tol_minus")
    as_found_value = val.require_number(body, "as_found_value")
    as_left_value = val.optional_number(body, "as_left_value", default=as_found_value)

    # State: only DRAFT/IN_PROGRESS events accept points (PRD §3.3)
    if event["status"] not in ("DRAFT", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Event does not accept measurement points")

    as_found_pass = calc.point_pass(as_found_value, nominal, tol_minus, tol_plus)
    as_left_pass = calc.point_pass(as_left_value, nominal, tol_minus, tol_plus)

    row = common_fields()
    row.update({
        "calibration_event_id": eid,
        "point_label": point_label,
        "nominal": nominal,
        "tol_plus": tol_plus,
        "tol_minus": tol_minus,
        "as_found_value": as_found_value,
        "as_left_value": as_left_value,
        "as_found_pass": as_found_pass,
        "as_left_pass": as_left_pass,
    })
    db.measurement_points[row["id"]] = row
    return success(ser.serialize_point(row), 201)


@app.route("/calibration-events/<eid>/measurement-points", methods=["GET"])
def list_points(eid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.calibration_events, eid)
    rows = [p for p in db.measurement_points.values()
            if p["calibration_event_id"] == eid]
    return paginate(rows, ser.serialize_point)


# ===========================================================================
# Certificates
# ===========================================================================
def _cert_number_unique(vendor_id, certificate_number, exclude_id=None):
    for c in db.certificates.values():
        if c["id"] == exclude_id:
            continue
        if (c["vendor_id"] == vendor_id
                and c["certificate_number"] == certificate_number
                and c["status"] != "REJECTED"):
            return False
    return True


@app.route("/calibration-events/<eid>/certificates", methods=["POST"])
def create_certificate(eid):
    require_auth(["Metrologist"])
    event = get_or_404(db.calibration_events, eid)
    body = get_json()
    # FK existence: vendor_id (404)
    vendor_id = body.get("vendor_id")
    if not isinstance(vendor_id, str) or vendor_id == "":
        raise err("ERR_INVALID_REQUEST", "vendor_id is required")
    if vendor_id not in db.calibration_vendors:
        raise err("ERR_FK_NOT_FOUND", "vendor_id does not exist")
    # Request validity (422)
    certificate_number = val.require_string(body, "certificate_number")
    issued_epoch = val.require_int(body, "issued_epoch")
    # Duplicate certificate number among vendor's non-REJECTED certs (409)
    if not _cert_number_unique(vendor_id, certificate_number):
        raise err("ERR_DUPLICATE_CERTIFICATE_NUMBER",
                  "certificate_number already used by this vendor")

    row = common_fields()
    row.update({
        "calibration_event_id": eid,
        "vendor_id": vendor_id,
        "certificate_number": certificate_number,
        "issued_epoch": issued_epoch,
        "status": "ISSUED",
    })
    db.certificates[row["id"]] = row
    return success(ser.serialize_certificate(row), 201)


@app.route("/calibration-events/<eid>/certificates", methods=["GET"])
def list_event_certificates(eid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.calibration_events, eid)
    rows = [c for c in db.certificates.values()
            if c["calibration_event_id"] == eid]
    return paginate(rows, ser.serialize_certificate)


@app.route("/certificates/<cid>", methods=["GET"])
def get_certificate(cid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    row = get_or_404(db.certificates, cid)
    return success(ser.serialize_certificate(row), 200)


@app.route("/certificates", methods=["GET"])
def list_certificates():
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    rows = list(db.certificates.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    return paginate(rows, ser.serialize_certificate)


@app.route("/certificates/<cid>/verify", methods=["POST"])
def verify_certificate(cid):
    require_auth(["Metrologist"])
    cert = get_or_404(db.certificates, cid)
    # State: ISSUED (409)
    if cert["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Certificate is not ISSUED")
    event = db.calibration_events[cert["calibration_event_id"]]
    # Owning event PASSED/CONDITIONAL_PASS (409)
    if event["status"] not in ("PASSED", "CONDITIONAL_PASS"):
        raise err("ERR_EVENT_NOT_FINALIZED", "Owning event is not finalized")
    # vendor match (409)
    if cert["vendor_id"] != event.get("vendor_id"):
        raise err("ERR_CERT_VENDOR_MISMATCH",
                  "Certificate vendor does not match event vendor")
    # vendor accreditation current (409)
    vendor = db.calibration_vendors[cert["vendor_id"]]
    if not ser.vendor_is_accreditation_current(vendor):
        raise err("ERR_VENDOR_NOT_ELIGIBLE", "Vendor accreditation is not current")
    cert["status"] = "VERIFIED"
    touch(cert)
    return success(ser.serialize_certificate(cert), 200)


@app.route("/certificates/<cid>/reject", methods=["POST"])
def reject_certificate(cid):
    require_auth(["Metrologist"])
    cert = get_or_404(db.certificates, cid)
    if cert["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Certificate is not ISSUED")
    cert["status"] = "REJECTED"
    touch(cert)
    return success(ser.serialize_certificate(cert), 200)


@app.route("/certificates/<cid>/reissue", methods=["POST"])
def reissue_certificate(cid):
    require_auth(["Metrologist"])
    cert = get_or_404(db.certificates, cid)
    if cert["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Certificate is not REJECTED")
    body = get_json()
    new_number = cert["certificate_number"]
    if "certificate_number" in body and body.get("certificate_number") is not None:
        new_number = val.require_string(body, "certificate_number")
    # Unique among vendor's non-REJECTED certs (409), excluding self.
    if not _cert_number_unique(cert["vendor_id"], new_number, exclude_id=cid):
        raise err("ERR_DUPLICATE_CERTIFICATE_NUMBER",
                  "certificate_number already used by this vendor")
    cert["certificate_number"] = new_number
    cert["status"] = "ISSUED"
    touch(cert)
    return success(ser.serialize_certificate(cert), 200)


# ===========================================================================
# Out-of-Tolerance Impacts
# ===========================================================================
@app.route("/instruments/<iid>/impacts", methods=["GET"])
def list_instrument_impacts(iid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.instruments, iid)
    rows = [i for i in db.impacts.values() if i["instrument_id"] == iid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.serialize_impact)


@app.route("/impacts/<pid>", methods=["GET"])
def get_impact(pid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    row = get_or_404(db.impacts, pid)
    return success(ser.serialize_impact(row), 200)


@app.route("/impacts", methods=["GET"])
def list_impacts():
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    rows = list(db.impacts.values())
    tev = request.args.get("triggering_event_id")
    if tev is not None:
        rows = [r for r in rows if r["triggering_event_id"] == tev]
    return paginate(rows, ser.serialize_impact)


@app.route("/impacts/<pid>/exposure", methods=["GET"])
def impact_exposure(pid):
    require_auth(["QualityEngineer", "Metrologist"])
    impact = get_or_404(db.impacts, pid)
    basis = request.args.get("basis", "CONSERVATIVE")
    if basis not in ("CONSERVATIVE", "MEASURED"):
        raise err("ERR_INVALID_REQUEST", "basis must be CONSERVATIVE or MEASURED")
    products = [ap for ap in db.affected_products.values()
                if ap["impact_id"] == pid]
    start = impact["suspect_window_start_epoch"]
    end = impact["suspect_window_end_epoch"]
    prior = impact.get("prior_calibration_epoch")
    if basis == "CONSERVATIVE":
        count = sum(1 for ap in products
                    if start <= ap["measured_epoch"] <= end)
    else:  # MEASURED — half-open (prior, end]; prior None -> treat as start-1
        lower = prior if prior is not None else (start - 1)
        count = sum(1 for ap in products
                    if lower < ap["measured_epoch"] <= end)
    return success({
        "exposure_count": count,
        "basis": basis,
        "suspect_window_start_epoch": start,
        "suspect_window_end_epoch": end,
    }, 200)


@app.route("/impacts/<pid>/investigate", methods=["POST"])
def investigate_impact(pid):
    user_id, role = require_auth(["QualityEngineer"])
    impact = get_or_404(db.impacts, pid)
    # State: OPEN or ESCALATED (409)
    if impact["status"] not in ("OPEN", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "Impact cannot be investigated from its state")
    # Segregation of duties (403) — acting user != triggering event author.
    event = db.calibration_events[impact["triggering_event_id"]]
    if user_id == event["performed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Acting user performed the triggering calibration")
    impact["status"] = "INVESTIGATING"
    touch(impact)
    return success(ser.serialize_impact(impact), 200)


@app.route("/impacts/<pid>/disposition", methods=["POST"])
def disposition_impact(pid):
    user_id, role = require_auth(["QualityEngineer"])
    impact = get_or_404(db.impacts, pid)
    body = get_json()
    disposition = val.require_enum(
        body, "disposition", {"USE_AS_IS", "REWORK", "RECALL", "SCRAP"})
    # State: INVESTIGATING (409)
    if impact["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "Impact is not INVESTIGATING")
    # Segregation of duties (403)
    event = db.calibration_events[impact["triggering_event_id"]]
    if user_id == event["performed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Acting user performed the triggering calibration")
    products = [ap for ap in db.affected_products.values()
                if ap["impact_id"] == pid]
    # RECALL needs >= 1 in-window product (409)
    if disposition == "RECALL":
        if not any(ap["in_suspect_window"] for ap in products):
            raise err("ERR_NO_RECALLABLE_PRODUCT",
                      "No affected product is in the suspect window")

    impact["disposition"] = disposition
    impact["dispositioned_by_user_id"] = user_id
    impact["status"] = "DISPOSITIONED"

    if disposition == "RECALL":
        for ap in products:
            if ap["in_suspect_window"]:
                ap["status"] = "RECALLED"
                touch(ap)
    else:
        for ap in products:
            if ap["status"] == "FLAGGED":
                ap["status"] = "CLEARED"
                touch(ap)

    touch(impact)
    # Bubble up open_oot_count
    inst = db.instruments[impact["instrument_id"]]
    _sync_open_oot_count(inst)
    return success(ser.serialize_impact(impact), 200)


@app.route("/impacts/<pid>/escalate", methods=["POST"])
def escalate_impact(pid):
    require_auth(["QualityEngineer"])
    impact = get_or_404(db.impacts, pid)
    if impact["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "Impact is not INVESTIGATING")
    impact["status"] = "ESCALATED"
    touch(impact)
    return success(ser.serialize_impact(impact), 200)


@app.route("/impacts/<pid>/cancel", methods=["POST"])
def cancel_impact(pid):
    require_auth(["QualityEngineer"])
    impact = get_or_404(db.impacts, pid)
    # State: OPEN (409)
    if impact["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Impact is not OPEN")
    # No product already RECALLED (409)
    for ap in db.affected_products.values():
        if ap["impact_id"] == pid and ap["status"] == "RECALLED":
            raise err("ERR_RECALL_ALREADY_ISSUED",
                      "A product has already been recalled")
    impact["status"] = "CANCELLED"
    touch(impact)
    inst = db.instruments[impact["instrument_id"]]
    _sync_open_oot_count(inst)
    return success(ser.serialize_impact(impact), 200)


# ===========================================================================
# Affected Products
# ===========================================================================
@app.route("/impacts/<pid>/affected-products", methods=["POST"])
def create_affected_product(pid):
    require_auth(["QualityEngineer"])
    impact = get_or_404(db.impacts, pid)
    body = get_json()
    product_serial = val.require_string(body, "product_serial")
    measured_epoch = val.require_int(body, "measured_epoch")

    start = impact["suspect_window_start_epoch"]
    end = impact["suspect_window_end_epoch"]
    in_window = start <= measured_epoch <= end

    row = common_fields()
    row.update({
        "impact_id": pid,
        "product_serial": product_serial,
        "measured_epoch": measured_epoch,
        "in_suspect_window": in_window,
        "status": "FLAGGED",
    })
    db.affected_products[row["id"]] = row
    return success(ser.serialize_affected_product(row), 201)


@app.route("/impacts/<pid>/affected-products", methods=["GET"])
def list_affected_products(pid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.impacts, pid)
    rows = [ap for ap in db.affected_products.values() if ap["impact_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.serialize_affected_product)


# ===========================================================================
# Gage R&R Studies
# ===========================================================================
@app.route("/instruments/<iid>/gage-rr-studies", methods=["POST"])
def create_study(iid):
    require_auth(["QualityEngineer"])
    inst = get_or_404(db.instruments, iid)
    body = get_json()
    operator_count = val.require_int(body, "operator_count")
    part_count = val.require_int(body, "part_count")
    trial_count = val.require_int(body, "trial_count")
    process_tolerance = val.require_number(body, "process_tolerance")
    expected_version = val.require_int(body, "expected_instrument_version")
    if not (2 <= operator_count <= 4):
        raise err("ERR_INVALID_REQUEST", "operator_count must be between 2 and 4")
    if not (2 <= part_count <= 10):
        raise err("ERR_INVALID_REQUEST", "part_count must be between 2 and 10")
    if not (2 <= trial_count <= 4):
        raise err("ERR_INVALID_REQUEST", "trial_count must be between 2 and 4")
    if process_tolerance <= 0:
        raise err("ERR_INVALID_REQUEST", "process_tolerance must be > 0")

    # Retired guard
    if inst["lifecycle_status"] == "RETIRED":
        raise err("ERR_INSTRUMENT_RETIRED", "Instrument is retired")
    # OCC (412)
    if expected_version != inst["version"]:
        raise err("ERR_STALE_INSTRUMENT_VERSION",
                  "expected_instrument_version does not match current version")

    row = common_fields()
    row.update({
        "instrument_id": iid,
        "operator_count": operator_count,
        "part_count": part_count,
        "trial_count": trial_count,
        "process_tolerance": process_tolerance,
        "ev_repeatability": None,
        "av_reproducibility": None,
        "grr": None,
        "pct_grr": None,
        "acceptability": None,
        "status": "DRAFT",
    })
    db.gage_rr_studies[row["id"]] = row
    touch(inst)
    return success(ser.serialize_study(row), 201)


@app.route("/instruments/<iid>/gage-rr-studies", methods=["GET"])
def list_instrument_studies(iid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.instruments, iid)
    rows = [s for s in db.gage_rr_studies.values() if s["instrument_id"] == iid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.serialize_study)


@app.route("/gage-rr-studies/<sid>", methods=["GET"])
def get_study(sid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    row = get_or_404(db.gage_rr_studies, sid)
    return success(ser.serialize_study(row), 200)


@app.route("/gage-rr-studies/<sid>/trials", methods=["POST"])
def create_trial(sid):
    require_auth(["QualityEngineer", "Technician"])
    study = get_or_404(db.gage_rr_studies, sid)
    body = get_json()
    operator_index = val.require_int(body, "operator_index")
    part_index = val.require_int(body, "part_index")
    trial_index = val.require_int(body, "trial_index")
    measured_value = val.require_number(body, "measured_value")

    # Bounds + duplicate cell (409) — ERR_DUPLICATE_TRIAL_CELL
    in_bounds = (
        1 <= operator_index <= study["operator_count"]
        and 1 <= part_index <= study["part_count"]
        and 1 <= trial_index <= study["trial_count"]
    )
    if not in_bounds:
        raise err("ERR_DUPLICATE_TRIAL_CELL", "Trial index out of declared bounds")
    for t in db.gage_rr_trials.values():
        if (t["study_id"] == sid
                and t["operator_index"] == operator_index
                and t["part_index"] == part_index
                and t["trial_index"] == trial_index):
            raise err("ERR_DUPLICATE_TRIAL_CELL", "Trial cell already populated")

    row = common_fields()
    row.update({
        "study_id": sid,
        "operator_index": operator_index,
        "part_index": part_index,
        "trial_index": trial_index,
        "measured_value": measured_value,
    })
    db.gage_rr_trials[row["id"]] = row
    return success(ser.serialize_trial(row), 201)


@app.route("/gage-rr-studies/<sid>/trials", methods=["GET"])
def list_trials(sid):
    require_auth(["QualityEngineer", "Technician", "Metrologist"])
    get_or_404(db.gage_rr_studies, sid)
    rows = [t for t in db.gage_rr_trials.values() if t["study_id"] == sid]
    return paginate(rows, ser.serialize_trial)


@app.route("/gage-rr-studies/<sid>/open", methods=["POST"])
def open_study(sid):
    require_auth(["QualityEngineer"])
    study = get_or_404(db.gage_rr_studies, sid)
    inst = db.instruments[study["instrument_id"]]
    # State: DRAFT (409)
    if study["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Study is not DRAFT")
    # Instrument ACTIVE (409)
    if inst["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INSTRUMENT_NOT_ACTIVE", "Instrument is not ACTIVE")
    study["status"] = "COLLECTING"
    touch(study)
    return success(ser.serialize_study(study), 200)


@app.route("/gage-rr-studies/<sid>/analyze", methods=["POST"])
def analyze_study(sid):
    require_auth(["QualityEngineer"])
    study = get_or_404(db.gage_rr_studies, sid)
    # State: COLLECTING (409)
    if study["status"] != "COLLECTING":
        raise err("ERR_INVALID_STATE", "Study is not COLLECTING")
    trials = [t for t in db.gage_rr_trials.values() if t["study_id"] == sid]
    expected = study["operator_count"] * study["part_count"] * study["trial_count"]
    cells = set()
    for t in trials:
        cells.add((t["operator_index"], t["part_index"], t["trial_index"]))
    # Complete matrix: exactly expected count, one per cell, no gaps/duplicates.
    if len(trials) != expected or len(cells) != expected:
        raise err("ERR_INCOMPLETE_TRIAL_MATRIX",
                  "Trial matrix is not exactly complete")

    metrics = calc.compute_gage_rr(
        trials, study["operator_count"], study["part_count"],
        study["trial_count"], study["process_tolerance"])
    study.update(metrics)
    study["status"] = "ANALYZED"
    touch(study)
    return success(ser.serialize_study(study), 200)


@app.route("/gage-rr-studies/<sid>/accept", methods=["POST"])
def accept_study(sid):
    require_auth(["QualityEngineer"])
    study = get_or_404(db.gage_rr_studies, sid)
    # State: ANALYZED (409)
    if study["status"] != "ANALYZED":
        raise err("ERR_INVALID_STATE", "Study is not ANALYZED")
    if study["acceptability"] == "UNACCEPTABLE":
        raise err("ERR_GAGE_RR_UNACCEPTABLE", "Gage R&R is unacceptable")
    study["status"] = "ACCEPTED"
    touch(study)
    return success(ser.serialize_study(study), 200)


@app.route("/gage-rr-studies/<sid>/reject", methods=["POST"])
def reject_study(sid):
    require_auth(["QualityEngineer"])
    study = get_or_404(db.gage_rr_studies, sid)
    if study["status"] != "ANALYZED":
        raise err("ERR_INVALID_STATE", "Study is not ANALYZED")
    study["status"] = "COLLECTING"
    study["ev_repeatability"] = None
    study["av_reproducibility"] = None
    study["grr"] = None
    study["pct_grr"] = None
    study["acceptability"] = None
    touch(study)
    return success(ser.serialize_study(study), 200)


@app.route("/gage-rr-studies/<sid>/cancel", methods=["POST"])
def cancel_study(sid):
    require_auth(["QualityEngineer"])
    study = get_or_404(db.gage_rr_studies, sid)
    if study["status"] not in ("DRAFT", "COLLECTING"):
        raise err("ERR_INVALID_STATE", "Study cannot be cancelled from its state")
    study["status"] = "CANCELLED"
    touch(study)
    return success(ser.serialize_study(study), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
