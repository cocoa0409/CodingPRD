"""Qualification endpoints: grant (unique per substitute/subject/band), list."""

from flask import Blueprint

from db import STORE, new_entity, public
from errors import raise_err, ERR_SUBSTITUTE_NOT_FOUND, ERR_DUPLICATE_QUALIFICATION
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from validate import body, req_str, req_enum

bp = Blueprint("qualifications", __name__)

GRADE_BANDS = ("ELEMENTARY", "MIDDLE", "HIGH")


@bp.route("/qualifications", methods=["POST"])
def create_qualification():
    _, role = auth_context()
    data = body()
    substitute_id = req_str(data, "substitute_id")
    subject = req_str(data, "subject")
    grade_band = req_enum(data, "grade_band", GRADE_BANDS)
    require_role(role, ["DistrictAdmin"])
    if substitute_id not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    for q in STORE.qualifications.values():
        if (q["substitute_id"] == substitute_id and q["subject"] == subject
                and q["grade_band"] == grade_band):
            raise_err(ERR_DUPLICATE_QUALIFICATION,
                      "qualification already exists for (substitute, subject, grade_band)")
    q = new_entity(STORE.qualifications, {
        "substitute_id": substitute_id,
        "subject": subject,
        "grade_band": grade_band,
    }, common=False)
    return ok(public(q), status=201)


@bp.route("/substitutes/<sid>/qualifications", methods=["GET"])
def list_substitute_qualifications(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    items = sorted((q for q in STORE.qualifications.values() if q["substitute_id"] == sid),
                   key=lambda q: (q["created_at"], q["_seq"]))
    page, meta = paginated(items)
    return ok([public(q) for q in page], pagination=meta)
