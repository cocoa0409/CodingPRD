from datetime import timedelta

from flask import request

from core import (store, authorize, get_body, require_fields, require_string,
                  require_enum, respond_object, respond_list, base_common,
                  base_line_item, touch, serialize, serialize_many,
                  sort_by_created, paginate, parse_iso, ApiError)
from lookups import get_device, get_inspector, get_inspection, get_complaint
from services import (TESTABLE_STATES, DEVICE_BUFFER_MINUTES, evaluate_accuracy,
                      evaluate_scanner, finalize_pass, finalize_fail,
                      MIN_SAMPLE)

INSPECTION_TYPES = {"ACCURACY_TEST", "PRICE_VERIFICATION", "COMPLAINT_RETEST"}
NON_TERMINAL = {"SCHEDULED", "IN_PROGRESS"}


def _require_number(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "%s must be a number" % field)
    return v


def _require_int(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % field)
    return v


def register(app):

    @app.route("/inspections", methods=["POST"])
    def schedule_inspection():
        authorize(["Inspector", "ProgramAdmin"])
        body = get_body(optional=False)

        # ---- body validity (400) ----
        device_id = require_string(body, "device_id")
        inspector_id = require_string(body, "inspector_id")
        inspection_type = require_enum(body, "inspection_type", INSPECTION_TYPES)
        require_fields(body, ["scheduled_start", "scheduled_end", "expected_device_version"])
        expected_version = body["expected_device_version"]
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise ApiError("ERR_VALIDATION", "expected_device_version must be an integer")
        start_dt = parse_iso(body["scheduled_start"])
        end_dt = parse_iso(body["scheduled_end"])
        if not (end_dt > start_dt):
            raise ApiError("ERR_SCHEDULE_WINDOW_INVALID",
                           "scheduled_end must be strictly after scheduled_start")

        # ---- existence (404), left to right ----
        device = get_device(device_id)
        inspector = get_inspector(inspector_id)

        # ---- state: device testability (409) ----
        if device["status"] not in TESTABLE_STATES:
            raise ApiError("ERR_DEVICE_NOT_TESTABLE",
                           "Device is not in a testable state")

        # ---- OCC (412) ----
        if expected_version != device["version"]:
            raise ApiError("ERR_STALE_DEVICE_VERSION",
                           "expected_device_version does not match current device version")

        # ---- complaint linkage (409) ----
        complaint_id = None
        if inspection_type == "COMPLAINT_RETEST":
            cid = body.get("complaint_id")
            if not cid:
                raise ApiError("ERR_COMPLAINT_REQUIRED",
                               "COMPLAINT_RETEST requires a valid FILED complaint")
            complaint = store.complaints.get(cid)
            if (complaint is None or complaint["status"] != "FILED"
                    or complaint["device_id"] != device_id):
                raise ApiError("ERR_COMPLAINT_REQUIRED",
                               "COMPLAINT_RETEST requires a matching FILED complaint")
            complaint_id = cid

        # ---- inspector schedule conflict (409): half-open overlap ----
        for other in store.inspections.values():
            if other["inspector_id"] != inspector_id:
                continue
            if other["status"] not in NON_TERMINAL:
                continue
            os_, oe_ = other["_start_dt"], other["_end_dt"]
            if start_dt < oe_ and os_ < end_dt:
                raise ApiError("ERR_INSPECTOR_SCHEDULE_CONFLICT",
                               "Inspector already has an overlapping inspection")

        # ---- device re-test buffer (409): closed window + 60 min buffer ----
        buffer = timedelta(minutes=DEVICE_BUFFER_MINUTES)
        for other in store.inspections.values():
            if other["device_id"] != device_id:
                continue
            if other["status"] not in NON_TERMINAL:
                continue
            os_, oe_ = other["_start_dt"], other["_end_dt"]
            if start_dt < oe_ + buffer and os_ < end_dt + buffer:
                raise ApiError("ERR_DEVICE_RETEST_BUFFER",
                               "Device has another inspection within the 60-minute buffer")

        # ---- create ----
        insp = base_common("Inspection")
        insp.update({
            "device_id": device_id,
            "inspector_id": inspector_id,
            "complaint_id": complaint_id,
            "inspection_type": inspection_type,
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "status": "SCHEDULED",
            "outcome": None,
            "_start_dt": start_dt,
            "_end_dt": end_dt,
        })
        store.inspections[insp["id"]] = insp

        # reserve the device (OCC): bump its version
        touch(device)

        return respond_object(serialize(insp), 201)

    @app.route("/inspections/<iid>", methods=["GET"])
    def get_inspection_route(iid):
        authorize(["ProgramAdmin", "Inspector", "Establishment"])
        insp = get_inspection(iid)
        return respond_object(serialize(insp), 200)

    @app.route("/inspections", methods=["GET"])
    def list_inspections():
        authorize(["ProgramAdmin", "Inspector", "Establishment"])
        device_id = request.args.get("device_id")
        inspector_id = request.args.get("inspector_id")
        complaint_id = request.args.get("complaint_id")
        status = request.args.get("status")
        items = list(store.inspections.values())
        if device_id is not None:
            items = [i for i in items if i["device_id"] == device_id]
        if inspector_id is not None:
            items = [i for i in items if i["inspector_id"] == inspector_id]
        if complaint_id is not None:
            items = [i for i in items if i.get("complaint_id") == complaint_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)

    @app.route("/inspections/<iid>/start", methods=["POST"])
    def start_inspection(iid):
        authorize(["Inspector"])
        get_body(optional=True)
        insp = get_inspection(iid)
        if insp["status"] != "SCHEDULED":
            raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS",
                           "Inspection is not in a startable (SCHEDULED) state")
        device = store.devices.get(insp["device_id"])
        if device is None or device["status"] not in TESTABLE_STATES:
            raise ApiError("ERR_DEVICE_NOT_TESTABLE",
                           "Device is not in a testable state")
        insp["status"] = "IN_PROGRESS"
        touch(insp)
        return respond_object(serialize(insp), 200)

    @app.route("/inspections/<iid>/finalize", methods=["POST"])
    def finalize_inspection(iid):
        authorize(["Inspector"])
        get_body(optional=True)
        insp = get_inspection(iid)
        if insp["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS",
                           "Only an IN_PROGRESS inspection can be finalized")
        device = store.devices.get(insp["device_id"])
        est = store.establishments.get(device["establishment_id"]) if device else None

        itype = insp["inspection_type"]
        # ---- evidence sufficiency (422) ----
        if itype in ("ACCURACY_TEST", "COMPLAINT_RETEST"):
            readings = [r for r in store.test_readings.values()
                        if r["inspection_id"] == iid]
            if len(readings) < 1:
                raise ApiError("ERR_NO_READINGS",
                               "At least one test reading is required")
            outcome = evaluate_accuracy(insp, device)
        else:  # PRICE_VERIFICATION
            items = [i for i in store.audit_items.values()
                     if i["inspection_id"] == iid]
            if len(items) < MIN_SAMPLE:
                raise ApiError("ERR_INSUFFICIENT_SAMPLE",
                               "At least one audit item is required")
            outcome = evaluate_scanner(insp)

        if outcome == "PASS":
            if est is None or est["status"] != "ACTIVE":
                raise ApiError("ERR_ESTABLISHMENT_SUSPENDED",
                               "A passing inspection cannot seal a device of a suspended establishment")
            insp["outcome"] = "PASS"
            insp["status"] = "PASSED"
            touch(insp)
            finalize_pass(insp, device, est)
        else:
            insp["outcome"] = "FAIL"
            insp["status"] = "FAILED"
            touch(insp)
            finalize_fail(insp, device, est)

        return respond_object(serialize(insp), 200)

    @app.route("/inspections/<iid>/test-readings", methods=["POST"])
    def create_test_reading(iid):
        authorize(["Inspector"])
        body = get_body(optional=False)
        insp = get_inspection(iid)
        if insp["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS",
                           "Readings can only be recorded on an IN_PROGRESS inspection")
        applied_load = _require_number(body, "applied_load")
        indicated_value = _require_number(body, "indicated_value")
        reading = base_line_item("TestReading")
        reading.update({
            "inspection_id": iid,
            "applied_load": applied_load,
            "indicated_value": indicated_value,
            "error_grams": abs(indicated_value - applied_load),
        })
        store.test_readings[reading["id"]] = reading
        return respond_object(serialize(reading), 201)

    @app.route("/inspections/<iid>/test-readings", methods=["GET"])
    def list_test_readings(iid):
        authorize(["ProgramAdmin", "Inspector", "Establishment"])
        get_inspection(iid)
        items = [r for r in store.test_readings.values() if r["inspection_id"] == iid]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)

    @app.route("/inspections/<iid>/audit-items", methods=["POST"])
    def create_audit_item(iid):
        authorize(["Inspector"])
        body = get_body(optional=False)
        insp = get_inspection(iid)
        if insp["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS",
                           "Audit items can only be recorded on an IN_PROGRESS inspection")
        item_sku = require_string(body, "item_sku")
        posted = _require_int(body, "posted_price_cents")
        scanned = _require_int(body, "scanned_price_cents")
        item = base_line_item("ScannerAuditItem")
        item.update({
            "inspection_id": iid,
            "item_sku": item_sku,
            "posted_price_cents": posted,
            "scanned_price_cents": scanned,
            "overcharge_cents": max(0, scanned - posted),
        })
        store.audit_items[item["id"]] = item
        return respond_object(serialize(item), 201)

    @app.route("/inspections/<iid>/audit-items", methods=["GET"])
    def list_audit_items(iid):
        authorize(["ProgramAdmin", "Inspector", "Establishment"])
        get_inspection(iid)
        items = [i for i in store.audit_items.values() if i["inspection_id"] == iid]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)
