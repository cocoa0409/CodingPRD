"""Care assessment endpoints."""
from flask import request

from db import LOCK, get_db
from errors import APIError
from helpers import (new_entity, paginate, parse_pagination, require_body,
                     require_field, touch)
from middleware import require_roles
from response import list_success, success
from services import audit, care_assessment as ca_svc


def _serialize(a):
    return dict(a)


def register(app):

    @app.post("/elders/<eid>/care-assessments")
    @require_roles("Nurse")
    def create_assessment(user_id, role, eid):
        body = require_body()
        adl = require_field(body, "adl_score", int)
        cog = require_field(body, "cognitive_score", int)
        med = require_field(body, "medical_condition_score", int)
        if not (0 <= adl <= 100):
            raise APIError("ERR_VALIDATION", "adl_score out of range", 422)
        if not (0 <= cog <= 30):
            raise APIError("ERR_VALIDATION", "cognitive_score out of range", 422)
        if not (0 <= med <= 50):
            raise APIError("ERR_VALIDATION", "medical_condition_score out of range", 422)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            assessment = new_entity({
                "elder_id": eid,
                "adl_score": adl,
                "cognitive_score": cog,
                "medical_condition_score": med,
                "composite_score": None,
                "classification": None,
                "status": "DRAFT",
                "assessor_id": user_id,
                "approver_id": None,
                "effective_from": None,
                "due_for_reassessment_at": None,
            })
            db.care_assessments[assessment["id"]] = assessment
            audit.log(role, user_id, "CareAssessment", assessment["id"],
                      "CREATE", None, "DRAFT")
            return success(_serialize(assessment), status=201)

    @app.post("/care-assessments/<aid>/submit")
    @require_roles("Nurse")
    def submit_assessment(user_id, role, aid):
        with LOCK:
            db = get_db()
            a = db.care_assessments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", f"CareAssessment {aid} not found", 404)
            prev = a["status"]
            if prev != "DRAFT":
                raise APIError("ERR_INVALID_STATE",
                               f"Assessment is {prev}, expected DRAFT", 409)
            composite, classification = ca_svc.compute_composite_and_classification(
                a["adl_score"], a["cognitive_score"], a["medical_condition_score"])
            a["composite_score"] = composite
            a["classification"] = classification
            a["status"] = "PENDING_APPROVAL"
            touch(a)
            audit.log(role, user_id, "CareAssessment", a["id"],
                      "SUBMIT", prev, a["status"])
            return success(_serialize(a))

    @app.post("/care-assessments/<aid>/approve")
    @require_roles("Supervisor")
    def approve_assessment(user_id, role, aid):
        with LOCK:
            db = get_db()
            a = db.care_assessments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", f"CareAssessment {aid} not found", 404)
            ca_svc.approve(a, user_id, role)
            return success(_serialize(a))

    @app.post("/care-assessments/<aid>/reject")
    @require_roles("Supervisor")
    def reject_assessment(user_id, role, aid):
        with LOCK:
            db = get_db()
            a = db.care_assessments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", f"CareAssessment {aid} not found", 404)
            ca_svc.reject(a, user_id, role)
            return success(_serialize(a))

    @app.post("/care-assessments/<aid>/return-for-revision")
    @require_roles("Supervisor")
    def return_for_revision(user_id, role, aid):
        with LOCK:
            db = get_db()
            a = db.care_assessments.get(aid)
            if a is None:
                raise APIError("ERR_NOT_FOUND", f"CareAssessment {aid} not found", 404)
            ca_svc.return_for_revision(a, user_id, role)
            return success(_serialize(a))

    @app.get("/elders/<eid>/care-assessments")
    @require_roles("Admin", "Supervisor", "Nurse")
    def list_assessments(user_id, role, eid):
        limit, offset = parse_pagination()
        status_f = request.args.get("status")
        db = get_db()
        if db.elders.get(eid) is None:
            raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
        items = [a for a in db.care_assessments.values() if a["elder_id"] == eid]
        if status_f:
            items = [a for a in items if a["status"] == status_f]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize(a) for a in page], limit, offset, total)
