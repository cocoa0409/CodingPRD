"""Appointment routes including check-in and op-records."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import current_actor, require_auth
from ..calculations import compute_prep_lead_minutes
from ..clock import add_days, add_minutes, format_iso, now_dt, now_iso_ms, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.conflicts import check_appointment_conflicts
from ..services.validation import check_occ, require_keys, require_str
from ..store import LOCK, bump_version, common_fields_append_only, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


def _resolve_appointment_context(plan_id: str, project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = get_store().treatment_plans.get(plan_id)
    if not plan:
        raise ApiError("ERR_NOT_FOUND", "Plan not found")
    proj = get_store().projects.get(project_id)
    if not proj:
        raise ApiError("ERR_NOT_FOUND", "Project not found")
    return plan, proj


def _check_room_kind_and_anesthesia(proj: dict[str, Any], room: dict[str, Any], anesthesia_id: str | None) -> None:
    is_surgical = proj["category"] == "SURGICAL"
    if is_surgical and not anesthesia_id:
        raise ApiError("ERR_ANESTHESIA_REQUIREMENT_MISMATCH", "anesthesia required for SURGICAL")
    if (not is_surgical) and anesthesia_id:
        raise ApiError("ERR_ANESTHESIA_REQUIREMENT_MISMATCH", "anesthesia not allowed for non-SURGICAL")
    if is_surgical and room["room_kind"] != "SURGICAL_OR":
        raise ApiError("ERR_ROOM_KIND_MISMATCH", "SURGICAL_OR required")
    if (not is_surgical) and room["room_kind"] == "SURGICAL_OR":
        raise ApiError("ERR_ROOM_KIND_MISMATCH", "SURGICAL_OR only for SURGICAL")


def _check_plan_stale(plan: dict[str, Any]) -> None:
    snap = plan.get("locked_project_versions") or {}
    for pid, v in snap.items():
        proj = get_store().projects.get(pid)
        if not proj or int(proj["version"]) != int(v):
            raise ApiError("ERR_PLAN_STALE_REFERENCE", "project version drift since plan approval")


def register(app: Flask) -> None:
    # --- POST /aesthetics/appointments ---
    @app.route("/aesthetics/appointments", methods=["POST"])
    @require_auth("Consultant")
    def create_appointment():
        body = get_json_body()
        require_keys(body, ["plan_id", "project_id", "scheduled_start", "doctor_id", "nurse_id", "room_id", "equipment_ids"])
        with LOCK:
            plan, proj = _resolve_appointment_context(body["plan_id"], body["project_id"])
            if plan["status"] != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "plan must be APPROVED")
            # project must be referenced in plan items
            item_pids = {it["project_id"] for it in plan["items"]}
            if proj["id"] not in item_pids:
                raise ApiError("ERR_INVALID_INPUT", "project not in plan items")
            # plan stale check
            _check_plan_stale(plan)
            # doctor must equal attending_physician and remain in qualified_doctor_ids
            doctor_id = require_str(body["doctor_id"], "doctor_id")
            if doctor_id != plan.get("attending_physician_id"):
                raise ApiError("ERR_DOCTOR_NOT_QUALIFIED", "doctor must equal plan's attending physician")
            if doctor_id not in (proj.get("qualified_doctor_ids") or []):
                raise ApiError("ERR_DOCTOR_NOT_QUALIFIED", "doctor not qualified for project")
            # Project must be ON_SHELF at appointment-create time
            if proj["status"] != "ON_SHELF":
                raise ApiError("ERR_PROJECT_NOT_ON_SHELF", "project not on shelf")
            nurse_id = require_str(body["nurse_id"], "nurse_id")
            room_id = require_str(body["room_id"], "room_id")
            room = get_store().rooms.get(room_id)
            if not room:
                raise ApiError("ERR_NOT_FOUND", "Room not found")
            if not room["is_active"]:
                raise ApiError("ERR_INVALID_STATE", "Room not active")
            eq_ids = body["equipment_ids"]
            if not isinstance(eq_ids, list) or len(eq_ids) < 1:
                raise ApiError("ERR_INVALID_INPUT", "equipment_ids must be non-empty array")
            for e in eq_ids:
                if not isinstance(e, str) or e == "":
                    raise ApiError("ERR_INVALID_INPUT", "equipment_ids entries must be strings")
            anesthesia_id = body.get("anesthesia_resource_id")
            if anesthesia_id is not None and not isinstance(anesthesia_id, str):
                raise ApiError("ERR_INVALID_INPUT", "anesthesia_resource_id must be string")
            _check_room_kind_and_anesthesia(proj, room, anesthesia_id)
            sched_start = parse_iso(require_str(body["scheduled_start"], "scheduled_start"))
            prep_minutes = compute_prep_lead_minutes(proj)
            sched_end = add_minutes(sched_start, proj["duration_minutes"])
            prep_window_start = add_minutes(sched_start, -prep_minutes)
            candidate = {
                "doctor_id": doctor_id,
                "nurse_id": nurse_id,
                "room_id": room_id,
                "equipment_ids": list(eq_ids),
                "anesthesia_resource_id": anesthesia_id,
            }
            check_appointment_conflicts(candidate, prep_window_start, sched_start, sched_end)
            appt = common_fields_create()
            appt.update({
                "plan_id": plan["id"],
                "project_id": proj["id"],
                "scheduled_start": format_iso(sched_start),
                "scheduled_end": format_iso(sched_end),
                "prep_window_start": format_iso(prep_window_start),
                "doctor_id": doctor_id,
                "nurse_id": nurse_id,
                "room_id": room_id,
                "equipment_ids": list(eq_ids),
                "anesthesia_resource_id": anesthesia_id,
                "status": "SCHEDULED",
                "reschedule_count": 0,
            })
            get_store().appointments[appt["id"]] = appt
        return created(appt)

    # --- POST /aesthetics/appointments/{id}/reschedule ---
    @app.route("/aesthetics/appointments/<aid>/reschedule", methods=["POST"])
    @require_auth("Consultant")
    def reschedule_appointment(aid: str):
        body = get_json_body()
        require_keys(body, ["scheduled_start"])
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "only SCHEDULED can be rescheduled")
            check_occ(appt, body)
            if int(appt["reschedule_count"]) >= 3:
                raise ApiError("ERR_RESCHEDULE_LIMIT", "reschedule limit reached")
            plan = get_store().treatment_plans.get(appt["plan_id"])
            if not plan or plan["status"] != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "parent plan not APPROVED")
            _check_plan_stale(plan)
            proj = get_store().projects.get(appt["project_id"])
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            doctor_id = body.get("doctor_id") or appt["doctor_id"]
            nurse_id = body.get("nurse_id") or appt["nurse_id"]
            room_id = body.get("room_id") or appt["room_id"]
            eq_ids = body.get("equipment_ids") if "equipment_ids" in body else appt["equipment_ids"]
            if not isinstance(eq_ids, list) or len(eq_ids) < 1:
                raise ApiError("ERR_INVALID_INPUT", "equipment_ids must be non-empty")
            anesthesia_id = body.get("anesthesia_resource_id") if "anesthesia_resource_id" in body else appt.get("anesthesia_resource_id")
            room = get_store().rooms.get(room_id)
            if not room:
                raise ApiError("ERR_NOT_FOUND", "Room not found")
            if not room["is_active"]:
                raise ApiError("ERR_INVALID_STATE", "Room not active")
            _check_room_kind_and_anesthesia(proj, room, anesthesia_id)
            if doctor_id not in (proj.get("qualified_doctor_ids") or []):
                raise ApiError("ERR_DOCTOR_NOT_QUALIFIED", "doctor not qualified")
            sched_start = parse_iso(body["scheduled_start"])
            prep_minutes = compute_prep_lead_minutes(proj)
            sched_end = add_minutes(sched_start, proj["duration_minutes"])
            prep_window_start = add_minutes(sched_start, -prep_minutes)
            candidate = {
                "doctor_id": doctor_id,
                "nurse_id": nurse_id,
                "room_id": room_id,
                "equipment_ids": list(eq_ids),
                "anesthesia_resource_id": anesthesia_id,
            }
            check_appointment_conflicts(candidate, prep_window_start, sched_start, sched_end, exclude_id=aid)
            appt["scheduled_start"] = format_iso(sched_start)
            appt["scheduled_end"] = format_iso(sched_end)
            appt["prep_window_start"] = format_iso(prep_window_start)
            appt["doctor_id"] = doctor_id
            appt["nurse_id"] = nurse_id
            appt["room_id"] = room_id
            appt["equipment_ids"] = list(eq_ids)
            appt["anesthesia_resource_id"] = anesthesia_id
            appt["reschedule_count"] = int(appt["reschedule_count"]) + 1
            bump_version(appt)
        return ok(appt)

    # --- POST /aesthetics/appointments/{id}/cancel ---
    @app.route("/aesthetics/appointments/<aid>/cancel", methods=["POST"])
    @require_auth("Consultant")
    def cancel_appointment(aid: str):
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "only SCHEDULED can be cancelled")
            appt["status"] = "CANCELLED"
            bump_version(appt)
            write_audit("APPT_CANCELLED", "Appointment", aid)
        return ok(appt)

    # --- POST /aesthetics/appointments/{id}/check-in ---
    @app.route("/aesthetics/appointments/<aid>/check-in", methods=["POST"])
    @require_auth("Nurse")
    def check_in(aid: str):
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "must be SCHEDULED")
            now = now_dt()
            prep_start = parse_iso(appt["prep_window_start"])
            sched_end = parse_iso(appt["scheduled_end"])
            if not (prep_start <= now < sched_end):
                raise ApiError("ERR_CHECKIN_OUTSIDE_WINDOW", "outside [prep_window_start, scheduled_end)")
            appt["status"] = "CHECKED_IN"
            bump_version(appt)
            # Create OperativeRecord shell
            opr = common_fields_append_only()
            opr.update({
                "appointment_id": aid,
                "check_in_at": now_iso_ms(),
                "procedure_log": [],
                "consumable_usage": [],
                "vital_sign_attachments": [],
                "incidents": [],
                "post_photo_ids": [],
            })
            get_store().operative_records[opr["id"]] = opr
            get_store().op_record_by_appointment[aid] = opr["id"]
            write_audit("OP_CHECK_IN", "Appointment", aid)
        return ok(appt)

    # --- Op-records ---
    def _opr_for(aid: str) -> dict[str, Any]:
        oid = get_store().op_record_by_appointment.get(aid)
        if not oid:
            raise ApiError("ERR_NOT_FOUND", "Operative record not found")
        opr = get_store().operative_records.get(oid)
        if not opr:
            raise ApiError("ERR_NOT_FOUND", "Operative record not found")
        return opr

    @app.route("/aesthetics/appointments/<aid>/op-records/start", methods=["POST"])
    @require_auth("AttendingPhysician")
    def op_start(aid: str):
        user_id, _ = current_actor()
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "CHECKED_IN":
                raise ApiError("ERR_INVALID_STATE", "must be CHECKED_IN")
            if appt["doctor_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only the assigned doctor")
            opr = _opr_for(aid)
            opr["procedure_log"].append({"step_code": "START", "recorded_at": now_iso_ms(), "note": ""})
            appt["status"] = "IN_PROGRESS"
            bump_version(appt)
            write_audit("OP_START", "Appointment", aid)
        return ok(opr)

    @app.route("/aesthetics/appointments/<aid>/op-records/key-step", methods=["POST"])
    @require_auth("AttendingPhysician")
    def op_key_step(aid: str):
        body = get_json_body()
        require_keys(body, ["note"])
        user_id, _ = current_actor()
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE", "must be IN_PROGRESS")
            if appt["doctor_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only the assigned doctor")
            opr = _opr_for(aid)
            opr["procedure_log"].append({"step_code": "KEY_STEP", "recorded_at": now_iso_ms(), "note": require_str(body["note"], "note", allow_empty=True)})
        return ok(opr)

    @app.route("/aesthetics/appointments/<aid>/op-records/consumables", methods=["POST"])
    @require_auth("AttendingPhysician", "Nurse")
    def op_consumables(aid: str):
        body = get_json_body()
        require_keys(body, ["sku_id", "quantity"])
        user_id, role = current_actor()
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE", "must be IN_PROGRESS")
            if role == "AttendingPhysician" and appt["doctor_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only the assigned doctor")
            if role == "Nurse" and appt["nurse_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only the assigned nurse")
            sku_id = require_str(body["sku_id"], "sku_id")
            sku = get_store().consumable_skus.get(sku_id)
            if not sku:
                raise ApiError("ERR_NOT_FOUND", "SKU not found")
            q = body["quantity"]
            if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
                raise ApiError("ERR_INVALID_INPUT", "quantity must be positive int")
            lot = body.get("lot_number")
            if sku.get("requires_lot_tracking"):
                if not isinstance(lot, str) or lot == "":
                    raise ApiError("ERR_LOT_NUMBER_REQUIRED", "lot_number required for tracked SKU")
            opr = _opr_for(aid)
            entry = {"sku_id": sku_id, "lot_number": lot, "quantity": q, "recorded_at": now_iso_ms()}
            opr["consumable_usage"].append(entry)
            emit_sync_event("PHARMA_TRACE", "CONSUMABLE_USED", {"appointment_id": aid, "sku_id": sku_id, "quantity": q, "lot_number": lot})
        return ok(opr)

    @app.route("/aesthetics/appointments/<aid>/op-records/vitals", methods=["POST"])
    @require_auth("Nurse")
    def op_vitals(aid: str):
        body = get_json_body()
        require_keys(body, ["asset_id"])
        user_id, _ = current_actor()
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE", "must be IN_PROGRESS")
            if appt["nurse_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only assigned nurse")
            opr = _opr_for(aid)
            opr["vital_sign_attachments"].append(require_str(body["asset_id"], "asset_id"))
        return ok(opr)

    @app.route("/aesthetics/appointments/<aid>/op-records/incidents", methods=["POST"])
    @require_auth("AttendingPhysician", "Nurse")
    def op_incidents(aid: str):
        body = get_json_body()
        require_keys(body, ["severity", "note"])
        user_id, role = current_actor()
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE", "must be IN_PROGRESS")
            if role == "AttendingPhysician" and appt["doctor_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only assigned doctor")
            if role == "Nurse" and appt["nurse_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only assigned nurse")
            opr = _opr_for(aid)
            opr["incidents"].append({
                "severity": require_str(body["severity"], "severity"),
                "reported_at": now_iso_ms(),
                "note": require_str(body["note"], "note", allow_empty=True),
            })
            write_audit("OP_INCIDENT", "Appointment", aid)
        return ok(opr)

    @app.route("/aesthetics/appointments/<aid>/op-records/end", methods=["POST"])
    @require_auth("AttendingPhysician")
    def op_end(aid: str):
        body = get_json_body()
        user_id, _ = current_actor()
        with LOCK:
            appt = get_store().appointments.get(aid)
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            if appt["status"] != "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE", "must be IN_PROGRESS")
            if appt["doctor_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only the assigned doctor")
            opr = _opr_for(aid)
            # Validate exactly one START
            start_entries = [e for e in opr["procedure_log"] if e["step_code"] == "START"]
            if len(start_entries) != 1:
                raise ApiError("ERR_INVALID_STATE", "procedure_log must have exactly one START")
            # Lot-number requirement on all tracked SKU usages
            for cu in opr["consumable_usage"]:
                sku = get_store().consumable_skus.get(cu["sku_id"])
                if sku and sku.get("requires_lot_tracking"):
                    if not cu.get("lot_number"):
                        raise ApiError("ERR_LOT_NUMBER_REQUIRED", "lot_number missing")
            # Cumulative usage >= BOM requirement
            proj = get_store().projects.get(appt["project_id"])
            cumul: dict[str, int] = {}
            for cu in opr["consumable_usage"]:
                cumul[cu["sku_id"]] = cumul.get(cu["sku_id"], 0) + int(cu["quantity"])
            for bom in proj.get("bom") or []:
                if cumul.get(bom["sku_id"], 0) < int(bom["quantity"]):
                    raise ApiError("ERR_INVALID_STATE", f"BOM requirement not met for {bom['sku_id']}")
            # Attach post_photo_ids if provided
            if "post_photo_ids" in body:
                pids = body["post_photo_ids"]
                if not isinstance(pids, list):
                    raise ApiError("ERR_INVALID_INPUT", "post_photo_ids must be array")
                for p in pids:
                    if not isinstance(p, str):
                        raise ApiError("ERR_INVALID_INPUT", "post_photo_ids entries must be strings")
                opr["post_photo_ids"] = list(pids)
            # Append END
            opr["procedure_log"].append({"step_code": "END", "recorded_at": now_iso_ms(), "note": ""})
            appt["status"] = "COMPLETED"
            bump_version(appt)
            # Spawn 4 FollowUps
            end_dt = now_dt()
            for stage, days in (("D1", 1), ("W1", 7), ("M1", 30), ("M3", 90)):
                fu = common_fields_create()
                fu.update({
                    "appointment_id": aid,
                    "stage": stage,
                    "due_at": format_iso(add_days(end_dt, days)),
                    "channel": "IM",
                    "status": "PENDING",
                    "feedback": None,
                    "adverse_event_filed": False,
                })
                get_store().followups[fu["id"]] = fu
            # Emit PHARMA_TRACE events for every consumable usage
            for cu in opr["consumable_usage"]:
                emit_sync_event("PHARMA_TRACE", "CONSUMABLE_USED", {
                    "appointment_id": aid, "sku_id": cu["sku_id"], "quantity": cu["quantity"], "lot_number": cu.get("lot_number"),
                })
            write_audit("OP_END", "Appointment", aid)
        return ok(appt)

    # --- GET /aesthetics/appointments/{id} ---
    @app.route("/aesthetics/appointments/<aid>", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "Nurse", "Customer")
    def fetch_appointment(aid: str):
        appt = get_store().appointments.get(aid)
        if not appt:
            raise ApiError("ERR_NOT_FOUND", "Appointment not found")
        user_id, role = current_actor()
        if role == "Customer":
            plan = get_store().treatment_plans.get(appt["plan_id"])
            if not plan or plan["customer_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Customer can only access own appointment")
        return ok(appt)

    # --- GET /aesthetics/appointments ---
    @app.route("/aesthetics/appointments", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "Nurse", "FinanceOfficer")
    def list_appointments():
        limit, offset = parse_limit_offset()
        plan_id = parse_optional_str("plan_id")
        doc = parse_optional_str("doctor_id")
        room = parse_optional_str("room_id")
        st = parse_optional_str("status")
        items = list(get_store().appointments.values())
        if plan_id:
            items = [a for a in items if a["plan_id"] == plan_id]
        if doc:
            items = [a for a in items if a["doctor_id"] == doc]
        if room:
            items = [a for a in items if a["room_id"] == room]
        if st:
            items = [a for a in items if a["status"] == st]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
