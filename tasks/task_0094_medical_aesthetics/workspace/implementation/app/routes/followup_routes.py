"""Follow-up routes."""
from __future__ import annotations

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import current_actor, require_auth
from ..calculations import compute_customer_risk_score, map_feedback_to_ae_severity
from ..clock import now_dt, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.validation import require_keys
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import get_json_body, list_ok, ok


def register(app: Flask) -> None:
    @app.route("/aesthetics/followups/<fid>/remind", methods=["POST"])
    @require_auth("Nurse")
    def remind(fid: str):
        with LOCK:
            fu = get_store().followups.get(fid)
            if not fu:
                raise ApiError("ERR_NOT_FOUND", "FollowUp not found")
            if fu["status"] != "PENDING":
                raise ApiError("ERR_INVALID_STATE", "must be PENDING")
            now = now_dt()
            due = parse_iso(fu["due_at"])
            if now < due:
                raise ApiError("ERR_INVALID_STATE", "before due_at")
            fu["status"] = "REMINDED"
            bump_version(fu)
            emit_sync_event("IM", "FOLLOWUP_REMINDER", {"followup_id": fid})
            write_audit("FOLLOWUP_REMINDED", "FollowUp", fid)
        return ok(fu)

    @app.route("/aesthetics/followups/<fid>/feedback", methods=["POST"])
    @require_auth("Customer")
    def feedback(fid: str):
        body = get_json_body()
        require_keys(body, ["satisfaction"])
        user_id, _ = current_actor()
        with LOCK:
            fu = get_store().followups.get(fid)
            if not fu:
                raise ApiError("ERR_NOT_FOUND", "FollowUp not found")
            if fu["status"] != "REMINDED":
                raise ApiError("ERR_INVALID_STATE", "must be REMINDED")
            appt = get_store().appointments.get(fu["appointment_id"])
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            plan = get_store().treatment_plans.get(appt["plan_id"])
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["customer_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Customer can only submit own feedback")
            sat = body["satisfaction"]
            if not isinstance(sat, int) or isinstance(sat, bool) or not (1 <= sat <= 5):
                raise ApiError("ERR_INVALID_INPUT", "satisfaction must be int 1..5")
            symptoms = body.get("symptoms")
            if symptoms is not None and not isinstance(symptoms, list):
                raise ApiError("ERR_INVALID_INPUT", "symptoms must be array")
            notes = body.get("notes")
            if notes is not None and not isinstance(notes, str):
                raise ApiError("ERR_INVALID_INPUT", "notes must be string")
            feedback_obj = {"satisfaction": sat, "symptoms": list(symptoms or []), "notes": notes}
            fu["feedback"] = feedback_obj
            fu["status"] = "COMPLETED"
            bump_version(fu)
            # Determine AE
            severity = map_feedback_to_ae_severity(feedback_obj)
            if severity:
                ae = common_fields_create()
                ae.update({
                    "appointment_id": appt["id"],
                    "customer_id": plan["customer_id"],
                    "severity": severity,
                    "description": notes or "auto-generated from feedback",
                    "status": "OPEN",
                    "escalated_at": None,
                })
                if severity == "SEVERE":
                    ae["status"] = "ESCALATED"
                    from ..clock import now_iso_ms
                    ae["escalated_at"] = now_iso_ms()
                    cust = get_store().customers.get(plan["customer_id"])
                    if cust:
                        cust["adverse_event_count"] = int(cust.get("adverse_event_count") or 0) + 1
                        cust["risk_score"] = compute_customer_risk_score(cust)
                        bump_version(cust)
                    write_audit("AE_ESCALATED", "AdverseEvent", ae["id"])
                get_store().adverse_events[ae["id"]] = ae
                fu["adverse_event_filed"] = True
        return ok(fu)

    @app.route("/aesthetics/followups/<fid>", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "Nurse", "Customer")
    def fetch_followup(fid: str):
        fu = get_store().followups.get(fid)
        if not fu:
            raise ApiError("ERR_NOT_FOUND", "FollowUp not found")
        user_id, role = current_actor()
        if role == "Customer":
            appt = get_store().appointments.get(fu["appointment_id"])
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            plan = get_store().treatment_plans.get(appt["plan_id"])
            if not plan or plan["customer_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Customer can only access own followup")
        return ok(fu)

    @app.route("/aesthetics/followups", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "Nurse")
    def list_followups():
        limit, offset = parse_limit_offset()
        aid = parse_optional_str("appointment_id")
        stage = parse_optional_str("stage")
        st = parse_optional_str("status")
        items = list(get_store().followups.values())
        if aid:
            items = [f for f in items if f["appointment_id"] == aid]
        if stage:
            items = [f for f in items if f["stage"] == stage]
        if st:
            items = [f for f in items if f["status"] == st]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
