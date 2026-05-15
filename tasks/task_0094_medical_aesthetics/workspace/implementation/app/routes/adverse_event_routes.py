"""AdverseEvent routes."""
from __future__ import annotations

from flask import Flask

from ..audit import write_audit
from ..auth import current_actor, require_auth
from ..calculations import compute_customer_risk_score
from ..clock import now_iso_ms
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.validation import require_keys, require_str
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


_SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}


def register(app: Flask) -> None:
    @app.route("/aesthetics/adverse-events", methods=["POST"])
    @require_auth("AttendingPhysician", "Nurse")
    def create_ae():
        body = get_json_body()
        require_keys(body, ["appointment_id", "severity", "description"])
        user_id, role = current_actor()
        with LOCK:
            appt = get_store().appointments.get(body["appointment_id"])
            if not appt:
                raise ApiError("ERR_NOT_FOUND", "Appointment not found")
            sev = body["severity"]
            if sev not in _SEVERITIES:
                raise ApiError("ERR_INVALID_INPUT", "invalid severity")
            plan = get_store().treatment_plans.get(appt["plan_id"])
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            ae = common_fields_create()
            ae.update({
                "appointment_id": appt["id"],
                "customer_id": plan["customer_id"],
                "severity": sev,
                "description": require_str(body["description"], "description", allow_empty=True),
                "status": "OPEN",
                "escalated_at": None,
            })
            if sev == "SEVERE":
                ae["status"] = "ESCALATED"
                ae["escalated_at"] = now_iso_ms()
                cust = get_store().customers.get(plan["customer_id"])
                if cust:
                    cust["adverse_event_count"] = int(cust.get("adverse_event_count") or 0) + 1
                    cust["risk_score"] = compute_customer_risk_score(cust)
                    bump_version(cust)
                write_audit("AE_ESCALATED", "AdverseEvent", ae["id"])
            get_store().adverse_events[ae["id"]] = ae
            write_audit("AE_CREATED", "AdverseEvent", ae["id"], {"severity": sev})
        return created(ae)

    @app.route("/aesthetics/adverse-events/<aid>/escalate", methods=["POST"])
    @require_auth("AttendingPhysician", "SeniorPhysician")
    def escalate(aid: str):
        with LOCK:
            ae = get_store().adverse_events.get(aid)
            if not ae:
                raise ApiError("ERR_NOT_FOUND", "AdverseEvent not found")
            if ae["status"] != "OPEN":
                raise ApiError("ERR_INVALID_STATE", "must be OPEN")
            ae["status"] = "ESCALATED"
            ae["escalated_at"] = now_iso_ms()
            bump_version(ae)
            cust = get_store().customers.get(ae["customer_id"])
            if cust:
                cust["adverse_event_count"] = int(cust.get("adverse_event_count") or 0) + 1
                cust["risk_score"] = compute_customer_risk_score(cust)
                bump_version(cust)
            write_audit("AE_ESCALATED", "AdverseEvent", aid)
        return ok(ae)

    @app.route("/aesthetics/adverse-events/<aid>/close", methods=["POST"])
    @require_auth("AttendingPhysician", "SeniorPhysician")
    def close_ae(aid: str):
        _, role = current_actor()
        with LOCK:
            ae = get_store().adverse_events.get(aid)
            if not ae:
                raise ApiError("ERR_NOT_FOUND", "AdverseEvent not found")
            if ae["status"] == "OPEN":
                # Only attending may close OPEN, and severity must be MINOR
                if role != "AttendingPhysician":
                    raise ApiError("ERR_FORBIDDEN", "Only attending may close OPEN")
                if ae["severity"] != "MINOR":
                    raise ApiError("ERR_INVALID_STATE", "Only MINOR severity may close from OPEN")
            elif ae["status"] == "ESCALATED":
                if role != "SeniorPhysician":
                    raise ApiError("ERR_FORBIDDEN", "Only senior may close ESCALATED")
            else:
                raise ApiError("ERR_INVALID_STATE", f"cannot close from {ae['status']}")
            ae["status"] = "CLOSED"
            bump_version(ae)
            write_audit("AE_CLOSED", "AdverseEvent", aid)
        return ok(ae)

    @app.route("/aesthetics/adverse-events", methods=["GET"])
    @require_auth("AttendingPhysician", "SeniorPhysician", "MedicalDirector")
    def list_ae():
        limit, offset = parse_limit_offset()
        cid = parse_optional_str("customer_id")
        sev = parse_optional_str("severity")
        st = parse_optional_str("status")
        items = list(get_store().adverse_events.values())
        if cid:
            items = [a for a in items if a["customer_id"] == cid]
        if sev:
            items = [a for a in items if a["severity"] == sev]
        if st:
            items = [a for a in items if a["status"] == st]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
