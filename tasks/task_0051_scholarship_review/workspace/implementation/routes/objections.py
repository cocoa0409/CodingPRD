"""Objection submit / get / rule."""
from flask import Blueprint, g

import db
from clock import parse_iso, now
from errors import err
from middleware import require_auth
from response import success
from services.audit import emit_audit, emit_external_sync
from services.lookup import (
    get_scholarship_or_404, get_objection_or_404, check_version,
)
from services.scholarship_lifecycle import transition_application
from services.validation import get_body


bp = Blueprint("objections", __name__)


VALID_REASON_CODES = {"MATERIAL_FALSE", "SCORING_ERROR", "ELIGIBILITY_BREACH", "COI_BREACH"}


@bp.route("/scholarships/<scholarship_id>/objections", methods=["POST"])
@require_auth(roles={"Student"})
def submit_objection(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    body = get_body()

    if s["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", "Scholarship must be ANNOUNCED for objection submission")
    if now() >= parse_iso(s["announcement_window_end"]):
        raise err("ERR_WINDOW_CLOSED", "announcement_window_end has elapsed")

    for f in ("application_id", "reason_code", "description"):
        if f not in body:
            raise err("ERR_BAD_REQUEST", f"Missing required field: {f}")
    if body["reason_code"] not in VALID_REASON_CODES:
        raise err("ERR_BAD_REQUEST", f"unknown reason_code: {body['reason_code']}")

    target_app = db.applications.get(body["application_id"])
    if target_app is None or target_app["scholarship_id"] != s["id"]:
        raise err("ERR_NOT_FOUND", "Target application not found in this scholarship")

    entity = {
        "application_id": target_app["id"],
        "objector_student_id": body.get("objector_student_id") or g.user_id,
        "reason_code": body["reason_code"],
        "description": body["description"],
        "status": "PENDING",
        "ruling_comment": None,
    }
    db.stamp_create(entity, common_fields=True)
    db.objections[entity["id"]] = entity
    return success(db.public(entity), 201)


@bp.route("/scholarships/<scholarship_id>/objections/<objection_id>", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "Student"})
def get_objection(scholarship_id, objection_id):
    get_scholarship_or_404(scholarship_id)
    o = get_objection_or_404(scholarship_id, objection_id)
    return success(db.public(o), 200)


@bp.route("/scholarships/<scholarship_id>/objections/<objection_id>/rule", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def rule_objection(scholarship_id, objection_id):
    s = get_scholarship_or_404(scholarship_id)
    o = get_objection_or_404(scholarship_id, objection_id)
    body = get_body()
    check_version(o, body)

    if s["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", "Scholarship must be ANNOUNCED to rule on objection")
    if o["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Objection must be PENDING")

    decision = body.get("decision")
    if decision not in ("UPHOLD", "DISMISS"):
        raise err("ERR_BAD_REQUEST", "decision must be UPHOLD or DISMISS")

    if decision == "UPHOLD":
        if now() >= parse_iso(s["announcement_window_end"]):
            raise err("ERR_WINDOW_CLOSED", "announcement_window_end has elapsed")

    rc = body.get("ruling_comment", "")
    if not isinstance(rc, str) or rc.strip() == "":
        raise err("ERR_COMMENT_REQUIRED", "ruling_comment required")

    o["ruling_comment"] = rc

    if decision == "UPHOLD":
        o["status"] = "UPHELD"
        db.stamp_update(o)
        # Cascade: if target app currently AWARDED, transition AWARDED→REVOKED + promotion.
        target_app = db.applications.get(o["application_id"])
        if target_app is not None and target_app["status"] == "AWARDED":
            target_app["revocation_reason"] = "OBJECTION_UPHELD"
            # Decrement filled_slots on the slice
            slice_row = _find_slice_for(target_app)
            if slice_row is not None:
                slice_row["filled_slots"] = max(0, slice_row.get("filled_slots", 0) - 1)
                db.stamp_update(slice_row)
            transition_application(target_app, "REVOKED",
                                   actor_role="system", actor_id="system",
                                   event_type="OBJECTION_RULED",
                                   payload={"from": "AWARDED", "to": "REVOKED",
                                             "revocation_reason": "OBJECTION_UPHELD",
                                             "objection_id": o["id"]})
            # Single promotion cascade: highest-ranked NOT_AWARDED in same slice flips to AWARDED.
            if slice_row is not None:
                key = (slice_row["department_code"], slice_row["grade"], slice_row["special_group"])
                candidates = [
                    a for a in db.applications.values()
                    if a["scholarship_id"] == s["id"] and a["status"] == "NOT_AWARDED"
                    and (a["student_department_code"], a["student_grade"], a.get("student_special_group", "NONE")) == key
                ]
                if candidates:
                    # Tie-break per scaffold: descending aggregated_score_x100, then ascending student_id (lexical).
                    candidates.sort(key=lambda a: (-(a.get("aggregated_score_x100") or 0), a.get("student_id", "")))
                    promoted = candidates[0]
                    transition_application(promoted, "AWARDED",
                                           actor_role="system", actor_id="system",
                                           event_type=None,
                                           payload={"from": "NOT_AWARDED", "to": "AWARDED",
                                                     "via": "OBJECTION_PROMOTION",
                                                     "objection_id": o["id"]})
                    slice_row["filled_slots"] = slice_row.get("filled_slots", 0) + 1
                    db.stamp_update(slice_row)
        # IM_NOTIFY_OBJECTION_RULING for upheld
        emit_external_sync("IM_NOTIFY_OBJECTION_RULING", s["id"],
                           application_id=o["application_id"],
                           payload={"objection_id": o["id"], "decision": "UPHELD",
                                     "ruling_comment": rc})
        emit_audit("OBJECTION_RULED", "Objection", o["id"],
                   {"decision": "UPHOLD", "ruling_comment": rc,
                     "from": "PENDING", "to": "UPHELD"})
    else:
        o["status"] = "DISMISSED"
        db.stamp_update(o)
        emit_external_sync("IM_NOTIFY_OBJECTION_RULING", s["id"],
                           application_id=o["application_id"],
                           payload={"objection_id": o["id"], "decision": "DISMISSED",
                                     "ruling_comment": rc})
        emit_audit("OBJECTION_RULED", "Objection", o["id"],
                   {"decision": "DISMISS", "ruling_comment": rc,
                     "from": "PENDING", "to": "DISMISSED"})

    return success(db.public(o), 200)


def _find_slice_for(app: dict):
    for q in db.quota_allocations.values():
        if q["scholarship_id"] != app["scholarship_id"]:
            continue
        if q["department_code"] != app["student_department_code"]:
            continue
        if q["grade"] != app["student_grade"]:
            continue
        if q["special_group"] != app.get("student_special_group", "NONE"):
            continue
        return q
    return None
