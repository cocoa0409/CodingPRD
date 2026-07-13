from flask import Blueprint

import db
import core
import ser
import find
from core import ApiError

bp = Blueprint("assessments", __name__)

DIET_TYPES = {"NONE", "RENAL", "DIABETIC", "LOW_SODIUM", "PUREED"}


@bp.post("/clients/<cid>/assessments")
@core.require_auth(["Nutritionist"])
def create_assessment(cid):
    body = core.get_body()
    points = core.require_field(body, "nutrition_determine_points", "int")
    adl = core.require_field(body, "adl_score", "int")
    recommended = core.require_field(body, "recommended_meals_per_day", "int")
    diet_required = core.optional_field(body, "therapeutic_diet_required", "bool", default=False)
    diet_type = core.optional_field(body, "therapeutic_diet_type", "str", default="NONE")

    if not (0 <= points <= 21):
        core.invalid_value("nutrition_determine_points must be 0..21")
    if not (0 <= adl <= 6):
        core.invalid_value("adl_score must be 0..6")
    if not (1 <= recommended <= 3):
        core.invalid_value("recommended_meals_per_day must be 1..3")
    core.check_enum(diet_type, DIET_TYPES, "invalid therapeutic_diet_type")

    find.client(cid)

    rec = db.base_record()
    rec.update({
        "client_id": cid,
        "nutrition_determine_points": points,
        "nutrition_risk_category": core.compute_nutrition_risk(points),
        "adl_score": adl,
        "functional_level": core.compute_functional_level(adl),
        "therapeutic_diet_required": diet_required,
        "therapeutic_diet_type": diet_type,
        "recommended_meals_per_day": recommended,
        "status": "DRAFT",
    })
    db.assessments[rec["id"]] = rec
    return core.ok_object(ser.assessment(rec), 201)


@bp.get("/clients/<cid>/assessments")
@core.require_auth(core.ALL_ROLES)
def list_assessments(cid):
    find.client(cid)
    status = core.request.args.get("status")
    items = [a for a in db.assessments.values() if a["client_id"] == cid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.assessment(a) for a in page], limit, offset, total)


@bp.post("/assessments/<aid>/finalize")
@core.require_auth(["Nutritionist"])
def finalize_assessment(aid):
    a = find.assessment(aid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_ASSESSMENT_NOT_DRAFT", 409, "Assessment must be DRAFT to finalize")

    client_id = a["client_id"]
    # supersede any prior FINALIZED assessment for the same client
    for other in db.assessments.values():
        if other["id"] != aid and other["client_id"] == client_id and other["status"] == "FINALIZED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    a["status"] = "FINALIZED"
    db.touch(a)

    # advance the client INTAKE -> ASSESSED on first finalization
    c = db.clients.get(client_id)
    if c is not None and c["enrollment_status"] == "INTAKE":
        c["enrollment_status"] = "ASSESSED"
        db.touch(c)

    return core.ok_object(ser.assessment(a))
