"""Imaging Center Radiology API — Flask entry point.

In-memory, single-process. Store starts empty on every boot (no seeding).
All routes, error handlers, and bubble-up side effects live here so that the
cross-aggregate state propagation stays coordinated.
"""

import os

from flask import Flask, request

from db import db, lock
from errors import ApiError, err
from response import success, error_response
import helpers as h
import domain as dom

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = error_response(e.error_id, e.message)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    resp = error_response("ERR_NOT_FOUND", "Resource not found")
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    resp = error_response("ERR_NOT_FOUND", "Method not allowed")
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = error_response("ERR_VALIDATION", "Unexpected error: %s" % str(e))
    resp.status_code = 422
    return resp


# ---------------------------------------------------------------------------
# Auth + RBAC wrapper. Every handler calls auth(allowed_roles) first.
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    user_id, role = h.require_auth()
    h.require_role(role, allowed_roles)
    return user_id, role


ALL_ROLES = ["CenterAdmin", "SchedulingClerk", "Nurse", "Technologist", "Radiologist"]


# ===========================================================================
# ImagingCenter
# ===========================================================================
@app.route("/imaging-centers", methods=["POST"])
def create_center():
    with lock:
        auth(["CenterAdmin"])
        body = h.get_json_body()
        h.require_fields(body, ["name"])
        h.require_string(body["name"], "name")
        time_zone = body.get("time_zone", "UTC")
        if time_zone is None:
            time_zone = "UTC"
        h.require_string(time_zone, "time_zone")
        sla = body.get("critical_ack_sla_minutes", 60)
        if sla is None:
            sla = 60
        h.require_int(sla, "critical_ack_sla_minutes")
        threshold = body.get("repeat_rate_threshold_pct", 8.0)
        if threshold is None:
            threshold = 8.0
        h.require_number(threshold, "repeat_rate_threshold_pct")
        rec = {
            "name": body["name"],
            "time_zone": time_zone,
            "now_utc": "1970-01-01T00:00:00.000Z",
            "critical_ack_sla_minutes": sla,
            "repeat_rate_threshold_pct": float(threshold),
            "admin_locked": False,
            "posture": "OPEN",
            "total_acquired_series": 0,
            "total_repeat_reject_series": 0,
            "repeat_reject_rate_pct": 0.0,
        }
        db.stamp_new(rec)
        db.imaging_centers[rec["id"]] = rec
        return success(dom.ser_center(rec), 201)


@app.route("/imaging-centers/<cid>", methods=["GET"])
def get_center(cid):
    with lock:
        auth(ALL_ROLES)
        c = dom.get_or_404(db.imaging_centers, cid)
        return success(dom.ser_center(c), 200)


@app.route("/imaging-centers", methods=["GET"])
def list_centers():
    with lock:
        auth(["CenterAdmin"])
        limit, offset = h.parse_pagination()
        items = h.sort_by_creation(list(db.imaging_centers.values()))
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_center(x) for x in page], 200, pg)


@app.route("/imaging-centers/<cid>/lock", methods=["POST"])
def lock_center(cid):
    with lock:
        auth(["CenterAdmin"])
        c = dom.get_or_404(db.imaging_centers, cid)
        c["admin_locked"] = True
        dom.derive_posture(c)
        db.touch(c)
        return success(dom.ser_center(c), 200)


@app.route("/imaging-centers/<cid>/unlock", methods=["POST"])
def unlock_center(cid):
    with lock:
        auth(["CenterAdmin"])
        c = dom.get_or_404(db.imaging_centers, cid)
        c["admin_locked"] = False
        dom.derive_posture(c)
        db.touch(c)
        return success(dom.ser_center(c), 200)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    with lock:
        auth(["CenterAdmin"])
        body = h.get_json_body()
        h.require_fields(body, ["imaging_center_id", "to_iso8601"])
        c = dom.get_ref_or_404(db.imaging_centers, body["imaging_center_id"])
        dt = h.parse_iso(body["to_iso8601"], "to_iso8601")
        c["now_utc"] = h.iso_from_dt(dt)
        # Re-evaluate every CriticalResult SLA then re-derive posture.
        dom.recompute_all_critical_sla(c)
        dom.derive_posture(c)
        db.touch(c)
        return success(dom.ser_center(c), 200)


# ===========================================================================
# Modality
# ===========================================================================
@app.route("/imaging-centers/<cid>/modalities", methods=["POST"])
def create_modality(cid):
    with lock:
        auth(["CenterAdmin"])
        c = dom.get_or_404(db.imaging_centers, cid)
        body = h.get_json_body()
        h.require_fields(body, ["modality_type", "name", "base_rvu"])
        h.require_enum(body["modality_type"], dom.MODALITY_TYPES, "modality_type")
        h.require_string(body["name"], "name")
        h.require_number(body["base_rvu"], "base_rvu")
        if body["base_rvu"] < 0:
            raise err("ERR_INVALID_REQUEST", "base_rvu must be >= 0")
        rpa = body.get("requires_prior_auth", True)
        if rpa is None:
            rpa = True
        h.require_bool(rpa, "requires_prior_auth")
        mt = body["modality_type"]
        rec = {
            "imaging_center_id": c["id"],
            "modality_type": mt,
            "name": body["name"],
            "base_rvu": float(body["base_rvu"]),
            "requires_contrast_screening": mt in ("MRI", "CT"),
            "requires_prior_auth": rpa,
        }
        db.stamp_new(rec)
        db.modalities[rec["id"]] = rec
        return success(dom.ser_modality(rec), 201)


@app.route("/modalities/<mid>", methods=["GET"])
def get_modality(mid):
    with lock:
        auth(ALL_ROLES)
        m = dom.get_or_404(db.modalities, mid)
        return success(dom.ser_modality(m), 200)


@app.route("/imaging-centers/<cid>/modalities", methods=["GET"])
def list_center_modalities(cid):
    with lock:
        auth(ALL_ROLES)
        dom.get_or_404(db.imaging_centers, cid)
        limit, offset = h.parse_pagination()
        items = [m for m in db.modalities.values() if m["imaging_center_id"] == cid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_modality(x) for x in page], 200, pg)


@app.route("/modalities/<mid>/rooms", methods=["GET"])
def list_modality_rooms(mid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist"])
        dom.get_or_404(db.modalities, mid)
        limit, offset = h.parse_pagination()
        items = [r for r in db.rooms.values() if r["modality_id"] == mid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_room(x) for x in page], 200, pg)


@app.route("/modalities/<mid>/imaging-orders", methods=["GET"])
def list_modality_orders(mid):
    with lock:
        auth(ALL_ROLES)
        dom.get_or_404(db.modalities, mid)
        limit, offset = h.parse_pagination()
        status = request.args.get("status")
        items = [o for o in db.imaging_orders.values() if o["modality_id"] == mid]
        if status:
            items = [o for o in items if o["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_order(x) for x in page], 200, pg)


# ===========================================================================
# Room
# ===========================================================================
@app.route("/imaging-centers/<cid>/rooms", methods=["POST"])
def create_room(cid):
    with lock:
        auth(["CenterAdmin"])
        c = dom.get_or_404(db.imaging_centers, cid)
        body = h.get_json_body()
        h.require_fields(body, ["modality_id", "name"])
        h.require_string(body["modality_id"], "modality_id")
        h.require_string(body["name"], "name")
        buf = body.get("cleanup_buffer_minutes", 0)
        if buf is None:
            buf = 0
        h.require_int(buf, "cleanup_buffer_minutes")
        if buf < 0:
            raise err("ERR_INVALID_REQUEST", "cleanup_buffer_minutes must be >= 0")
        m = dom.get_ref_or_404(db.modalities, body["modality_id"])
        rec = {
            "imaging_center_id": c["id"],
            "modality_id": m["id"],
            "name": body["name"],
            "cleanup_buffer_minutes": buf,
            "status": "AVAILABLE",
        }
        db.stamp_new(rec)
        db.rooms[rec["id"]] = rec
        return success(dom.ser_room(rec), 201)


@app.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist"])
        r = dom.get_or_404(db.rooms, rid)
        return success(dom.ser_room(r), 200)


@app.route("/imaging-centers/<cid>/rooms", methods=["GET"])
def list_center_rooms(cid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist"])
        dom.get_or_404(db.imaging_centers, cid)
        limit, offset = h.parse_pagination()
        modality_filter = request.args.get("modality_id")
        items = [r for r in db.rooms.values() if r["imaging_center_id"] == cid]
        if modality_filter:
            items = [r for r in items if r["modality_id"] == modality_filter]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_room(x) for x in page], 200, pg)


@app.route("/rooms/<rid>/out-of-service", methods=["POST"])
def room_out_of_service(rid):
    with lock:
        auth(["CenterAdmin"])
        r = dom.get_or_404(db.rooms, rid)
        r["status"] = "OUT_OF_SERVICE"
        db.touch(r)
        return success(dom.ser_room(r), 200)


# ===========================================================================
# Staff
# ===========================================================================
@app.route("/imaging-centers/<cid>/staff", methods=["POST"])
def create_staff(cid):
    with lock:
        auth(["CenterAdmin"])
        c = dom.get_or_404(db.imaging_centers, cid)
        body = h.get_json_body()
        h.require_fields(body, ["staff_role", "full_name", "credentialed_modalities"])
        h.require_enum(body["staff_role"], {"TECHNOLOGIST", "RADIOLOGIST", "NURSE"}, "staff_role")
        h.require_string(body["full_name"], "full_name")
        creds = body["credentialed_modalities"]
        if not isinstance(creds, list):
            raise err("ERR_INVALID_REQUEST", "credentialed_modalities must be an array")
        for item in creds:
            if item not in dom.MODALITY_TYPES:
                raise err("ERR_INVALID_REQUEST", "Invalid modality in credentialed_modalities")
        # ERR_EMPTY_CREDENTIALS comes after generic body validity (priority 6).
        if len(creds) == 0:
            raise err("ERR_EMPTY_CREDENTIALS", "credentialed_modalities must be non-empty")
        rec = {
            "imaging_center_id": c["id"],
            "staff_role": body["staff_role"],
            "full_name": body["full_name"],
            "credentialed_modalities": list(creds),
            "signed_rvu_total": 0.0,
        }
        db.stamp_new(rec)
        db.staff[rec["id"]] = rec
        return success(dom.ser_staff(rec), 201)


@app.route("/staff/<sid>", methods=["GET"])
def get_staff(sid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist", "Radiologist"])
        s = dom.get_or_404(db.staff, sid)
        return success(dom.ser_staff(s), 200)


@app.route("/imaging-centers/<cid>/staff", methods=["GET"])
def list_center_staff(cid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist", "Radiologist"])
        dom.get_or_404(db.imaging_centers, cid)
        limit, offset = h.parse_pagination()
        role_filter = request.args.get("staff_role")
        items = [s for s in db.staff.values() if s["imaging_center_id"] == cid]
        if role_filter:
            items = [s for s in items if s["staff_role"] == role_filter]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_staff(x) for x in page], 200, pg)


# ===========================================================================
# ImagingOrder
# ===========================================================================
@app.route("/imaging-centers/<cid>/imaging-orders", methods=["POST"])
def create_order(cid):
    with lock:
        auth(["SchedulingClerk"])
        c = dom.get_or_404(db.imaging_centers, cid)
        body = h.get_json_body()
        h.require_fields(body, ["modality_id", "patient_mrn", "ordering_provider_npi"])
        h.require_string(body["modality_id"], "modality_id")
        h.require_string(body["patient_mrn"], "patient_mrn")
        h.require_string(body["ordering_provider_npi"], "ordering_provider_npi")
        priority = body.get("priority", "ROUTINE")
        if priority is None:
            priority = "ROUTINE"
        h.require_enum(priority, {"STAT", "ROUTINE"}, "priority")
        requires_contrast = body.get("requires_contrast", False)
        if requires_contrast is None:
            requires_contrast = False
        h.require_bool(requires_contrast, "requires_contrast")
        m = dom.get_ref_or_404(db.modalities, body["modality_id"])
        rec = {
            "imaging_center_id": c["id"],
            "modality_id": m["id"],
            "patient_mrn": body["patient_mrn"],
            "ordering_provider_npi": body["ordering_provider_npi"],
            "priority": priority,
            "requires_contrast": requires_contrast,
            "status": "REQUESTED",
            "report_turnaround_minutes": None,
            "turnaround_met": None,
        }
        db.stamp_new(rec)
        db.imaging_orders[rec["id"]] = rec
        return success(dom.ser_order(rec), 201)


@app.route("/imaging-orders/<oid>", methods=["GET"])
def get_order(oid):
    with lock:
        auth(ALL_ROLES)
        o = dom.get_or_404(db.imaging_orders, oid)
        return success(dom.ser_order(o), 200)


@app.route("/imaging-centers/<cid>/imaging-orders", methods=["GET"])
def list_center_orders(cid):
    with lock:
        auth(ALL_ROLES)
        dom.get_or_404(db.imaging_centers, cid)
        limit, offset = h.parse_pagination()
        status = request.args.get("status")
        items = [o for o in db.imaging_orders.values() if o["imaging_center_id"] == cid]
        if status:
            items = [o for o in items if o["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_order(x) for x in page], 200, pg)


def _order_modality(order):
    return db.modalities[order["modality_id"]]


def _prior_auths_for_order(oid):
    return [p for p in db.prior_authorizations.values() if p["imaging_order_id"] == oid]


def _screenings_for_order(oid):
    return [s for s in db.contrast_screenings.values() if s["imaging_order_id"] == oid]


@app.route("/imaging-orders/<oid>/benefit-check", methods=["POST"])
def benefit_check(oid):
    with lock:
        auth(["SchedulingClerk"])
        o = dom.get_or_404(db.imaging_orders, oid)
        body = h.get_json_body()
        copay = body.get("benefit_copay_cents")
        if copay is not None:
            h.require_int(copay, "benefit_copay_cents")
        # State gate (priority 7)
        if o["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Order not in REQUESTED")
        modality = _order_modality(o)
        auths = _prior_auths_for_order(oid)
        if modality["requires_prior_auth"]:
            authorized = [p for p in auths if p["status"] == "AUTHORIZED"]
            if not authorized:
                raise err("ERR_PRIOR_AUTH_REQUIRED",
                          "An AUTHORIZED prior authorization is required")
            target_auth = authorized[0]
            if copay is not None:
                target_auth["benefit_copay_cents"] = copay
                db.touch(target_auth)
        else:
            # requires_prior_auth false: skip auth check. Set copay on an
            # existing auth if present; otherwise default 0 (nothing to set).
            if auths:
                target_auth = auths[0]
                target_auth["benefit_copay_cents"] = copay if copay is not None else 0
                db.touch(target_auth)
        o["status"] = "BENEFIT_CHECKED"
        db.touch(o)
        return success(dom.ser_order(o), 200)


@app.route("/imaging-orders/<oid>/clear-screening", methods=["POST"])
def clear_screening(oid):
    with lock:
        auth(["Nurse"])
        o = dom.get_or_404(db.imaging_orders, oid)
        if o["status"] != "BENEFIT_CHECKED":
            raise err("ERR_INVALID_STATE", "Order not in BENEFIT_CHECKED")
        modality = _order_modality(o)
        if modality["requires_contrast_screening"]:
            screenings = _screenings_for_order(oid)
            cleared = [s for s in screenings if s["outcome"] == "CLEARED"]
            if not cleared:
                raise err("ERR_SCREENING_NOT_CLEARED",
                          "A CLEARED contrast screening is required")
        o["status"] = "SCREEN_CLEARED"
        db.touch(o)
        return success(dom.ser_order(o), 200)


@app.route("/imaging-orders/<oid>/exams", methods=["POST"])
def schedule_exam(oid):
    with lock:
        auth(["SchedulingClerk"])
        o = dom.get_or_404(db.imaging_orders, oid)
        body = h.get_json_body()
        h.require_fields(body, ["room_id", "technologist_id", "scheduled_start_utc",
                                "scheduled_end_utc", "expected_imaging_order_version"])
        h.require_string(body["room_id"], "room_id")
        h.require_string(body["technologist_id"], "technologist_id")
        h.require_int(body["expected_imaging_order_version"], "expected_imaging_order_version")
        start_dt = h.parse_iso(body["scheduled_start_utc"], "scheduled_start_utc")
        end_dt = h.parse_iso(body["scheduled_end_utc"], "scheduled_end_utc")
        # FK existence (priority 4)
        room = dom.get_ref_or_404(db.rooms, body["room_id"])
        tech = dom.get_ref_or_404(db.staff, body["technologist_id"])
        # State (priority 7)
        if o["status"] != "SCREEN_CLEARED":
            raise err("ERR_INVALID_STATE", "Order not in SCREEN_CLEARED")
        # OCC (priority 8)
        if body["expected_imaging_order_version"] != o["version"]:
            raise err("ERR_STALE_VERSION", "Order version is stale")
        modality = _order_modality(o)
        # Tech credential (priority 14)
        if modality["modality_type"] not in tech["credentialed_modalities"]:
            raise err("ERR_TECH_NOT_CREDENTIALED",
                      "Technologist not credentialed on order's modality")
        # Room modality match + not out of service (priority 15)
        if room["modality_id"] != o["modality_id"] or room["status"] == "OUT_OF_SERVICE":
            raise err("ERR_ROOM_MODALITY_MISMATCH",
                      "Room modality mismatch or out of service")
        # Interval validity (priority 16)
        if not (end_dt > start_dt):
            raise err("ERR_INVALID_INTERVAL", "scheduled_end_utc must be after start")
        start_ms = h.epoch_ms(start_dt)
        end_ms = h.epoch_ms(end_dt)
        buf_ms = room["cleanup_buffer_minutes"] * 60000.0
        # Room overlap (priority 17): room occupied across [start, end+buffer)
        room_block_end = end_ms + buf_ms
        for ex in db.imaging_exams.values():
            if ex["room_id"] != room["id"]:
                continue
            if ex["status"] == "CANCELLED":
                continue
            ex_start = h.epoch_ms(h.parse_iso(ex["scheduled_start_utc"]))
            ex_end = h.epoch_ms(h.parse_iso(ex["scheduled_end_utc"]))
            ex_buf = db.rooms[ex["room_id"]]["cleanup_buffer_minutes"] * 60000.0
            ex_block_end = ex_end + ex_buf
            if start_ms < ex_block_end and ex_start < room_block_end:
                raise err("ERR_ROOM_DOUBLE_BOOKED", "Room booking interval overlaps")
        # Tech overlap (priority 18): no buffer
        for ex in db.imaging_exams.values():
            if ex["technologist_id"] != tech["id"]:
                continue
            if ex["status"] == "CANCELLED":
                continue
            ex_start = h.epoch_ms(h.parse_iso(ex["scheduled_start_utc"]))
            ex_end = h.epoch_ms(h.parse_iso(ex["scheduled_end_utc"]))
            if start_ms < ex_end and ex_start < end_ms:
                raise err("ERR_TECH_DOUBLE_BOOKED", "Technologist interval overlaps")
        exam = {
            "imaging_order_id": o["id"],
            "room_id": room["id"],
            "technologist_id": tech["id"],
            "radiologist_id": None,
            "scheduled_start_utc": h.iso_from_dt(start_dt),
            "scheduled_end_utc": h.iso_from_dt(end_dt),
            "acquired_at_utc": None,
            "signed_off_at_utc": None,
            "status": "BOOKED",
        }
        db.stamp_new(exam)
        db.imaging_exams[exam["id"]] = exam
        # Order advances SCREEN_CLEARED -> SCHEDULED; version bumps.
        o["status"] = "SCHEDULED"
        db.touch(o)
        return success(dom.ser_exam(exam), 201)


@app.route("/imaging-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    with lock:
        auth(["SchedulingClerk"])
        o = dom.get_or_404(db.imaging_orders, oid)
        if o["status"] in ("SIGNED_OFF", "ADDENDUM_REQUESTED", "CANCELLED"):
            raise err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
        o["status"] = "CANCELLED"
        db.touch(o)
        # Cascade-cancel a pre-ACQUIRED exam (BOOKED/CHECKED_IN).
        for ex in db.imaging_exams.values():
            if ex["imaging_order_id"] == oid and ex["status"] in ("BOOKED", "CHECKED_IN"):
                ex["status"] = "CANCELLED"
                db.touch(ex)
        return success(dom.ser_order(o), 200)


@app.route("/imaging-orders/<oid>/request-addendum", methods=["POST"])
def request_addendum(oid):
    with lock:
        auth(["Radiologist"])
        o = dom.get_or_404(db.imaging_orders, oid)
        if o["status"] != "SIGNED_OFF":
            raise err("ERR_INVALID_STATE", "Order not in SIGNED_OFF")
        report = _report_for_order(o)
        if report is None or report["status"] not in ("FINAL", "AMENDED"):
            raise err("ERR_REPORT_NOT_FINAL", "Report is not FINAL or AMENDED")
        # Reopen report to DRAFT, bump addendum_count.
        report["status"] = "DRAFT"
        report["addendum_count"] = report["addendum_count"] + 1
        db.touch(report)
        o["status"] = "ADDENDUM_REQUESTED"
        db.touch(o)
        return success(dom.ser_order(o), 200)


def _exam_for_order(order):
    exams = [e for e in db.imaging_exams.values()
             if e["imaging_order_id"] == order["id"] and e["status"] != "CANCELLED"]
    if not exams:
        return None
    return h.sort_by_creation(exams)[-1]


def _report_for_order(order):
    exam = _exam_for_order(order)
    if exam is None:
        return None
    return _report_for_exam(exam)


def _report_for_exam(exam):
    reports = [r for r in db.radiology_reports.values()
               if r["imaging_exam_id"] == exam["id"]]
    if not reports:
        return None
    return h.sort_by_creation(reports)[-1]


# ===========================================================================
# PriorAuthorization
# ===========================================================================
@app.route("/imaging-orders/<oid>/prior-authorizations", methods=["POST"])
def create_prior_auth(oid):
    with lock:
        auth(["SchedulingClerk"])
        o = dom.get_or_404(db.imaging_orders, oid)
        body = h.get_json_body()
        h.require_fields(body, ["payer_name", "requested_units"])
        h.require_string(body["payer_name"], "payer_name")
        h.require_int(body["requested_units"], "requested_units")
        if body["requested_units"] < 1:
            raise err("ERR_INVALID_REQUEST", "requested_units must be >= 1")
        rec = {
            "imaging_order_id": o["id"],
            "payer_name": body["payer_name"],
            "requested_units": body["requested_units"],
            "authorized_units": 0,
            "benefit_copay_cents": 0,
            "status": "PENDING",
        }
        db.stamp_new(rec)
        db.prior_authorizations[rec["id"]] = rec
        return success(dom.ser_prior_auth(rec), 201)


@app.route("/prior-authorizations/<pid>", methods=["GET"])
def get_prior_auth(pid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk"])
        p = dom.get_or_404(db.prior_authorizations, pid)
        return success(dom.ser_prior_auth(p), 200)


@app.route("/imaging-orders/<oid>/prior-authorizations", methods=["GET"])
def list_order_prior_auths(oid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk"])
        dom.get_or_404(db.imaging_orders, oid)
        limit, offset = h.parse_pagination()
        items = h.sort_by_creation(_prior_auths_for_order(oid))
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_prior_auth(x) for x in page], 200, pg)


@app.route("/prior-authorizations/<pid>/decision", methods=["POST"])
def prior_auth_decision(pid):
    with lock:
        auth(["SchedulingClerk"])
        p = dom.get_or_404(db.prior_authorizations, pid)
        body = h.get_json_body()
        h.require_fields(body, ["decision"])
        h.require_enum(body["decision"], {"AUTHORIZE", "DENY"}, "decision")
        au = body.get("authorized_units")
        if au is not None:
            h.require_int(au, "authorized_units")
        if p["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Prior authorization not in PENDING")
        if body["decision"] == "AUTHORIZE":
            if au is None:
                raise err("ERR_INVALID_REQUEST", "authorized_units required for AUTHORIZE")
            if au < p["requested_units"]:
                raise err("ERR_INSUFFICIENT_AUTH_UNITS",
                          "authorized_units below requested_units")
            p["authorized_units"] = au
            p["status"] = "AUTHORIZED"
        else:
            p["authorized_units"] = 0
            p["status"] = "DENIED"
        db.touch(p)
        return success(dom.ser_prior_auth(p), 200)


# ===========================================================================
# ContrastScreening
# ===========================================================================
@app.route("/imaging-orders/<oid>/contrast-screenings", methods=["POST"])
def create_screening(oid):
    with lock:
        auth(["Nurse"])
        o = dom.get_or_404(db.imaging_orders, oid)
        body = h.get_json_body()
        h.require_fields(body, ["egfr_value"])
        h.require_number(body["egfr_value"], "egfr_value")
        allergy = body.get("has_contrast_allergy", False)
        if allergy is None:
            allergy = False
        h.require_bool(allergy, "has_contrast_allergy")
        pregnant = body.get("is_pregnant", False)
        if pregnant is None:
            pregnant = False
        h.require_bool(pregnant, "is_pregnant")
        metal = body.get("metal_implant_unsafe", False)
        if metal is None:
            metal = False
        h.require_bool(metal, "metal_implant_unsafe")
        rec = {
            "imaging_order_id": o["id"],
            "egfr_value": float(body["egfr_value"]),
            "has_contrast_allergy": allergy,
            "is_pregnant": pregnant,
            "metal_implant_unsafe": metal,
            "outcome": "PENDING",
            "blocking_reason": None,
        }
        db.stamp_new(rec)
        db.contrast_screenings[rec["id"]] = rec
        return success(dom.ser_screening(rec), 201)


@app.route("/contrast-screenings/<sid>", methods=["GET"])
def get_screening(sid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Nurse"])
        s = dom.get_or_404(db.contrast_screenings, sid)
        return success(dom.ser_screening(s), 200)


@app.route("/imaging-orders/<oid>/contrast-screenings", methods=["GET"])
def list_order_screenings(oid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Nurse"])
        dom.get_or_404(db.imaging_orders, oid)
        limit, offset = h.parse_pagination()
        items = h.sort_by_creation(_screenings_for_order(oid))
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_screening(x) for x in page], 200, pg)


@app.route("/contrast-screenings/<sid>/evaluate", methods=["POST"])
def evaluate_screening(sid):
    with lock:
        auth(["Nurse"])
        s = dom.get_or_404(db.contrast_screenings, sid)
        if s["outcome"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Screening not in PENDING")
        order = db.imaging_orders[s["imaging_order_id"]]
        modality = _order_modality(order)
        outcome, reason = dom.screening_decision(s, order, modality)
        s["outcome"] = outcome
        s["blocking_reason"] = reason
        db.touch(s)
        return success(dom.ser_screening(s), 200)


# ===========================================================================
# ImagingExam
# ===========================================================================
@app.route("/imaging-exams/<eid>", methods=["GET"])
def get_exam(eid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist", "Radiologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        return success(dom.ser_exam(e), 200)


@app.route("/imaging-orders/<oid>/exams", methods=["GET"])
def list_order_exams(oid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist", "Radiologist"])
        dom.get_or_404(db.imaging_orders, oid)
        limit, offset = h.parse_pagination()
        items = [e for e in db.imaging_exams.values() if e["imaging_order_id"] == oid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_exam(x) for x in page], 200, pg)


@app.route("/rooms/<rid>/exams", methods=["GET"])
def list_room_exams(rid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist"])
        dom.get_or_404(db.rooms, rid)
        limit, offset = h.parse_pagination()
        items = [e for e in db.imaging_exams.values() if e["room_id"] == rid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_exam(x) for x in page], 200, pg)


@app.route("/staff/<sid>/exams", methods=["GET"])
def list_staff_exams(sid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk", "Technologist", "Radiologist"])
        dom.get_or_404(db.staff, sid)
        limit, offset = h.parse_pagination()
        assignment = request.args.get("assignment_role")
        items = []
        for e in db.imaging_exams.values():
            is_tech = e["technologist_id"] == sid
            is_rad = e["radiologist_id"] == sid
            if assignment == "TECHNOLOGIST":
                if is_tech:
                    items.append(e)
            elif assignment == "RADIOLOGIST":
                if is_rad:
                    items.append(e)
            else:
                if is_tech or is_rad:
                    items.append(e)
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_exam(x) for x in page], 200, pg)


@app.route("/imaging-exams/<eid>/check-in", methods=["POST"])
def exam_check_in(eid):
    with lock:
        user_id, role = auth(["Technologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        if e["status"] != "BOOKED":
            raise err("ERR_INVALID_STATE", "Exam not in BOOKED")
        if user_id != e["technologist_id"]:
            raise err("ERR_NOT_ASSIGNED_TECH", "Acting technologist is not assigned")
        center = _center_for_exam(e)
        now = dom.center_now_dt(center)
        start = h.parse_iso(e["scheduled_start_utc"])
        if h.epoch_ms(now) < h.epoch_ms(start):
            raise err("ERR_TOO_EARLY_TO_CHECK_IN", "Too early to check in")
        e["status"] = "CHECKED_IN"
        db.touch(e)
        return success(dom.ser_exam(e), 200)


@app.route("/imaging-exams/<eid>/start-acquisition", methods=["POST"])
def exam_start_acquisition(eid):
    with lock:
        user_id, role = auth(["Technologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        if e["status"] != "CHECKED_IN":
            raise err("ERR_INVALID_STATE", "Exam not in CHECKED_IN")
        if user_id != e["technologist_id"]:
            raise err("ERR_NOT_ASSIGNED_TECH", "Acting technologist is not assigned")
        center = _center_for_exam(e)
        if center["posture"] == "QUALITY_HOLD":
            raise err("ERR_CENTER_QUALITY_HOLD", "Center is in QUALITY_HOLD")
        e["status"] = "ACQUIRING"
        db.touch(e)
        return success(dom.ser_exam(e), 200)


@app.route("/imaging-exams/<eid>/finish-acquisition", methods=["POST"])
def exam_finish_acquisition(eid):
    with lock:
        user_id, role = auth(["Technologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        if e["status"] != "ACQUIRING":
            raise err("ERR_INVALID_STATE", "Exam not in ACQUIRING")
        if user_id != e["technologist_id"]:
            raise err("ERR_NOT_ASSIGNED_TECH", "Acting technologist is not assigned")
        series = [s for s in db.image_series.values() if s["imaging_exam_id"] == eid]
        if not any(s["outcome"] == "ACCEPTED" for s in series):
            raise err("ERR_NO_ACCEPTED_SERIES", "No ACCEPTED image series")
        if any(s["outcome"] == "CAPTURING" for s in series):
            raise err("ERR_SERIES_STILL_CAPTURING", "An image series is still CAPTURING")
        center = _center_for_exam(e)
        e["acquired_at_utc"] = center["now_utc"]
        e["status"] = "ACQUIRED"
        db.touch(e)
        # Bubble up: parent order SCHEDULED -> READ_PENDING
        order = db.imaging_orders[e["imaging_order_id"]]
        if order["status"] == "SCHEDULED":
            order["status"] = "READ_PENDING"
            db.touch(order)
        return success(dom.ser_exam(e), 200)


@app.route("/imaging-exams/<eid>/claim-read", methods=["POST"])
def exam_claim_read(eid):
    with lock:
        user_id, role = auth(["Radiologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        body = h.get_json_body()
        h.require_fields(body, ["expected_imaging_exam_version"])
        h.require_int(body["expected_imaging_exam_version"], "expected_imaging_exam_version")
        # State (priority 7)
        if e["status"] != "ACQUIRED":
            raise err("ERR_INVALID_STATE", "Exam not in ACQUIRED")
        # OCC (priority 8)
        if body["expected_imaging_exam_version"] != e["version"]:
            raise err("ERR_STALE_VERSION", "Exam version is stale")
        # Quality-hold not applicable here. Segregation of duties + credential.
        order = db.imaging_orders[e["imaging_order_id"]]
        modality = _order_modality(order)
        rad = dom.get_or_404(db.staff, user_id)
        if modality["modality_type"] not in rad["credentialed_modalities"]:
            raise err("ERR_RADIOLOGIST_NOT_CREDENTIALED",
                      "Radiologist not credentialed on order's modality")
        if user_id == e["technologist_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Reader must not be the acquiring technologist")
        if e["radiologist_id"] is not None:
            raise err("ERR_ALREADY_CLAIMED", "Exam already claimed")
        e["radiologist_id"] = user_id
        e["status"] = "READING"
        db.touch(e)
        return success(dom.ser_exam(e), 200)


@app.route("/imaging-exams/<eid>/sign-off", methods=["POST"])
def exam_sign_off(eid):
    with lock:
        user_id, role = auth(["Radiologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        if e["status"] != "READ_COMPLETE":
            raise err("ERR_INVALID_STATE", "Exam not in READ_COMPLETE")
        if user_id != e["radiologist_id"]:
            raise err("ERR_NOT_ASSIGNED_RADIOLOGIST", "Acting radiologist is not assigned")
        report = _report_for_exam(e)
        if report is not None and report["has_critical_finding"]:
            criticals = [c for c in db.critical_results.values()
                         if c["radiology_report_id"] == report["id"]]
            if not criticals:
                raise err("ERR_CRITICAL_RESULT_REQUIRED",
                          "Critical result required before sign-off")
        center = _center_for_exam(e)
        order = db.imaging_orders[e["imaging_order_id"]]
        modality = _order_modality(order)
        e["signed_off_at_utc"] = center["now_utc"]
        e["status"] = "SIGNED_OFF"
        db.touch(e)
        # RVU credit (first sign-off: amend_factor 1.0)
        rvu = dom.compute_rvu(modality, order, amended=False)
        report["rvu_credited"] = rvu
        db.touch(report)
        rad = db.staff.get(report["radiologist_id"])
        if rad is not None:
            rad["signed_rvu_total"] = h.round2(rad["signed_rvu_total"] + rvu)
            db.touch(rad)
        # Bubble up: order READ_PENDING -> SIGNED_OFF; compute turnaround.
        if order["status"] == "READ_PENDING":
            order["status"] = "SIGNED_OFF"
            order["report_turnaround_minutes"] = dom.compute_turnaround(e)
            target = dom.turnaround_target(order, modality)
            order["turnaround_met"] = order["report_turnaround_minutes"] <= target
            db.touch(order)
        return success(dom.ser_exam(e), 200)


@app.route("/imaging-exams/<eid>/cancel", methods=["POST"])
def cancel_exam(eid):
    with lock:
        auth(["SchedulingClerk"])
        e = dom.get_or_404(db.imaging_exams, eid)
        if e["status"] not in ("BOOKED", "CHECKED_IN"):
            raise err("ERR_INVALID_STATE", "Exam cannot be cancelled from its current state")
        e["status"] = "CANCELLED"
        db.touch(e)
        return success(dom.ser_exam(e), 200)


def _center_for_exam(exam):
    order = db.imaging_orders[exam["imaging_order_id"]]
    return db.imaging_centers[order["imaging_center_id"]]


# ===========================================================================
# ImageSeries
# ===========================================================================
@app.route("/imaging-exams/<eid>/image-series", methods=["POST"])
def create_series(eid):
    with lock:
        user_id, role = auth(["Technologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        body = h.get_json_body()
        h.require_fields(body, ["series_label"])
        h.require_string(body["series_label"], "series_label")
        if e["status"] != "ACQUIRING":
            raise err("ERR_INVALID_STATE", "Exam not in ACQUIRING")
        if user_id != e["technologist_id"]:
            raise err("ERR_NOT_ASSIGNED_TECH", "Acting technologist is not assigned")
        center = _center_for_exam(e)
        rec = {
            "imaging_exam_id": e["id"],
            "imaging_center_id": center["id"],
            "series_label": body["series_label"],
            "outcome": "CAPTURING",
            "reject_reason": None,
        }
        db.stamp_new(rec)
        db.image_series[rec["id"]] = rec
        return success(dom.ser_series(rec), 201)


@app.route("/image-series/<sid>", methods=["GET"])
def get_series(sid):
    with lock:
        auth(["CenterAdmin", "Technologist", "Radiologist"])
        s = dom.get_or_404(db.image_series, sid)
        return success(dom.ser_series(s), 200)


@app.route("/imaging-exams/<eid>/image-series", methods=["GET"])
def list_exam_series(eid):
    with lock:
        auth(["CenterAdmin", "Technologist", "Radiologist"])
        dom.get_or_404(db.imaging_exams, eid)
        limit, offset = h.parse_pagination()
        outcome = request.args.get("outcome")
        items = [s for s in db.image_series.values() if s["imaging_exam_id"] == eid]
        if outcome:
            items = [s for s in items if s["outcome"] == outcome]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_series(x) for x in page], 200, pg)


@app.route("/imaging-centers/<cid>/image-series", methods=["GET"])
def list_center_series(cid):
    with lock:
        auth(["CenterAdmin"])
        dom.get_or_404(db.imaging_centers, cid)
        limit, offset = h.parse_pagination()
        outcome = request.args.get("outcome")
        items = [s for s in db.image_series.values() if s["imaging_center_id"] == cid]
        if outcome:
            items = [s for s in items if s["outcome"] == outcome]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_series(x) for x in page], 200, pg)


@app.route("/image-series/<sid>/finalize", methods=["POST"])
def finalize_series(sid):
    with lock:
        user_id, role = auth(["Technologist"])
        s = dom.get_or_404(db.image_series, sid)
        body = h.get_json_body()
        h.require_fields(body, ["outcome"])
        h.require_enum(body["outcome"], {"ACCEPTED", "REPEATED", "REJECTED"}, "outcome")
        reject_reason = body.get("reject_reason")
        if reject_reason is not None and reject_reason not in dom.REJECT_REASONS:
            raise err("ERR_INVALID_REQUEST", "Invalid reject_reason")
        exam = db.imaging_exams[s["imaging_exam_id"]]
        # State checks (priority 7) — series CAPTURING and parent exam ACQUIRING.
        if s["outcome"] != "CAPTURING":
            raise err("ERR_INVALID_STATE", "Series not in CAPTURING")
        if exam["status"] != "ACQUIRING":
            raise err("ERR_INVALID_STATE", "Parent exam not in ACQUIRING")
        outcome = body["outcome"]
        if outcome in ("REPEATED", "REJECTED") and reject_reason is None:
            raise err("ERR_REJECT_REASON_REQUIRED", "reject_reason required")
        s["outcome"] = outcome
        if outcome in ("REPEATED", "REJECTED"):
            s["reject_reason"] = reject_reason
        else:
            s["reject_reason"] = None
        db.touch(s)
        # Center aggregate update + posture re-derivation.
        center = db.imaging_centers[s["imaging_center_id"]]
        center["total_acquired_series"] += 1
        if outcome in ("REPEATED", "REJECTED"):
            center["total_repeat_reject_series"] += 1
        dom.recompute_rate(center)
        dom.derive_posture(center)
        db.touch(center)
        return success(dom.ser_series(s), 200)


# ===========================================================================
# RadiologyReport
# ===========================================================================
@app.route("/imaging-exams/<eid>/reports", methods=["POST"])
def create_report(eid):
    with lock:
        user_id, role = auth(["Radiologist"])
        e = dom.get_or_404(db.imaging_exams, eid)
        body = h.get_json_body()
        h.require_fields(body, ["findings_text"])
        h.require_string(body["findings_text"], "findings_text")
        has_crit = body.get("has_critical_finding", False)
        if has_crit is None:
            has_crit = False
        h.require_bool(has_crit, "has_critical_finding")
        if e["status"] != "READING":
            raise err("ERR_INVALID_STATE", "Exam not in READING")
        if user_id != e["radiologist_id"]:
            raise err("ERR_NOT_ASSIGNED_RADIOLOGIST", "Acting radiologist is not assigned")
        rec = {
            "imaging_exam_id": e["id"],
            "radiologist_id": e["radiologist_id"],
            "findings_text": body["findings_text"],
            "has_critical_finding": has_crit,
            "rvu_credited": 0.0,
            "addendum_count": 0,
            "status": "DRAFT",
        }
        db.stamp_new(rec)
        db.radiology_reports[rec["id"]] = rec
        return success(dom.ser_report(rec), 201)


@app.route("/radiology-reports/<rid>", methods=["GET"])
def get_report(rid):
    with lock:
        auth(["CenterAdmin", "Radiologist", "SchedulingClerk"])
        r = dom.get_or_404(db.radiology_reports, rid)
        return success(dom.ser_report(r), 200)


@app.route("/imaging-exams/<eid>/reports", methods=["GET"])
def list_exam_reports(eid):
    with lock:
        auth(["CenterAdmin", "Radiologist", "SchedulingClerk"])
        dom.get_or_404(db.imaging_exams, eid)
        limit, offset = h.parse_pagination()
        items = [r for r in db.radiology_reports.values() if r["imaging_exam_id"] == eid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_report(x) for x in page], 200, pg)


@app.route("/staff/<sid>/reports", methods=["GET"])
def list_staff_reports(sid):
    with lock:
        auth(["CenterAdmin", "Radiologist"])
        dom.get_or_404(db.staff, sid)
        limit, offset = h.parse_pagination()
        items = [r for r in db.radiology_reports.values() if r["radiologist_id"] == sid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_report(x) for x in page], 200, pg)


@app.route("/radiology-reports/<rid>/finalize", methods=["POST"])
def finalize_report(rid):
    with lock:
        user_id, role = auth(["Radiologist"])
        r = dom.get_or_404(db.radiology_reports, rid)
        exam = db.imaging_exams[r["imaging_exam_id"]]
        # The report must be DRAFT (priority 7).
        if r["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Report not in DRAFT")
        if user_id != r["radiologist_id"]:
            raise err("ERR_NOT_ASSIGNED_RADIOLOGIST", "Acting radiologist is not assigned")
        is_amendment = r["addendum_count"] >= 1
        if not is_amendment:
            # First finalize: DRAFT -> FINAL, parent exam READING -> READ_COMPLETE.
            if exam["status"] != "READING":
                raise err("ERR_INVALID_STATE", "Parent exam not in READING")
            r["status"] = "FINAL"
            db.touch(r)
            exam["status"] = "READ_COMPLETE"
            db.touch(exam)
            return success(dom.ser_report(r), 200)
        # Amendment re-finalize: DRAFT (reopened) -> AMENDED.
        r["status"] = "AMENDED"
        db.touch(r)
        # Re-sign the exam: re-stamp signed_off_at_utc and recompute.
        order = db.imaging_orders[exam["imaging_order_id"]]
        modality = _order_modality(order)
        center = db.imaging_centers[order["imaging_center_id"]]
        exam["signed_off_at_utc"] = center["now_utc"]
        db.touch(exam)
        prior_rvu = r["rvu_credited"]
        new_rvu = dom.compute_rvu(modality, order, amended=True)
        r["rvu_credited"] = new_rvu
        db.touch(r)
        rad = db.staff.get(r["radiologist_id"])
        if rad is not None:
            rad["signed_rvu_total"] = h.round2(rad["signed_rvu_total"] + (new_rvu - prior_rvu))
            db.touch(rad)
        # Bubble up: order ADDENDUM_REQUESTED -> SIGNED_OFF; recompute turnaround.
        if order["status"] == "ADDENDUM_REQUESTED":
            order["status"] = "SIGNED_OFF"
            order["report_turnaround_minutes"] = dom.compute_turnaround(exam)
            target = dom.turnaround_target(order, modality)
            order["turnaround_met"] = order["report_turnaround_minutes"] <= target
            db.touch(order)
        return success(dom.ser_report(r), 200)


# ===========================================================================
# CriticalResult
# ===========================================================================
@app.route("/radiology-reports/<rid>/critical-results", methods=["POST"])
def raise_critical(rid):
    with lock:
        user_id, role = auth(["Radiologist"])
        r = dom.get_or_404(db.radiology_reports, rid)
        body = h.get_json_body()
        h.require_fields(body, ["notified_party_role"])
        h.require_enum(body["notified_party_role"],
                       {"ORDERING_PROVIDER", "COVERING_PROVIDER", "RAPID_RESPONSE"},
                       "notified_party_role")
        exam = db.imaging_exams[r["imaging_exam_id"]]
        center = _center_for_exam(exam)
        rec = {
            "radiology_report_id": r["id"],
            "imaging_center_id": center["id"],
            "notified_party_role": body["notified_party_role"],
            "raised_at_utc": center["now_utc"],
            "acknowledged_at_utc": None,
            "minutes_to_ack": None,
            "sla_breached": False,
            "status": "UNACKNOWLEDGED",
        }
        db.stamp_new(rec)
        db.critical_results[rec["id"]] = rec
        return success(dom.ser_critical(rec), 201)


@app.route("/critical-results/<cid>", methods=["GET"])
def get_critical(cid):
    with lock:
        auth(["CenterAdmin", "Radiologist", "SchedulingClerk"])
        c = dom.get_or_404(db.critical_results, cid)
        return success(dom.ser_critical(c), 200)


@app.route("/radiology-reports/<rid>/critical-results", methods=["GET"])
def list_report_criticals(rid):
    with lock:
        auth(["CenterAdmin", "Radiologist", "SchedulingClerk"])
        dom.get_or_404(db.radiology_reports, rid)
        limit, offset = h.parse_pagination()
        items = [c for c in db.critical_results.values()
                 if c["radiology_report_id"] == rid]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_critical(x) for x in page], 200, pg)


@app.route("/imaging-centers/<cid>/critical-results", methods=["GET"])
def list_center_criticals(cid):
    with lock:
        auth(["CenterAdmin", "SchedulingClerk"])
        dom.get_or_404(db.imaging_centers, cid)
        limit, offset = h.parse_pagination()
        status = request.args.get("status")
        items = [c for c in db.critical_results.values()
                 if c["imaging_center_id"] == cid]
        if status:
            items = [c for c in items if c["status"] == status]
        items = h.sort_by_creation(items)
        page, pg = h.paginate(items, limit, offset)
        return success([dom.ser_critical(x) for x in page], 200, pg)


@app.route("/critical-results/<cid>/acknowledge", methods=["POST"])
def acknowledge_critical(cid):
    with lock:
        user_id, role = auth(["Radiologist"])
        c = dom.get_or_404(db.critical_results, cid)
        if c["status"] != "UNACKNOWLEDGED":
            raise err("ERR_INVALID_STATE", "Critical result not in UNACKNOWLEDGED")
        center = db.imaging_centers[c["imaging_center_id"]]
        c["acknowledged_at_utc"] = center["now_utc"]
        raised = h.parse_iso(c["raised_at_utc"])
        acked = h.parse_iso(c["acknowledged_at_utc"])
        minutes = (h.epoch_ms(acked) - h.epoch_ms(raised)) / 60000.0
        c["minutes_to_ack"] = h.round2(minutes)
        c["sla_breached"] = c["minutes_to_ack"] > center["critical_ack_sla_minutes"]
        c["status"] = "ACKNOWLEDGED"
        db.touch(c)
        # Re-derive center posture (an ack may lift a safety-driven QUALITY_HOLD).
        dom.derive_posture(center)
        db.touch(center)
        return success(dom.ser_critical(c), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
