"""CleanlinessCertificate endpoints (PRD §2.5, §3.1)."""

from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_cert
from services import get_cert, cert_is_valid
from util import (
    GRADE_RANK,
    GRADES,
    as_enum,
    as_string,
    body_dict,
    parse_dt,
    req_present,
)

from routes import bp

SUBJECT_TYPES = {"MATERIAL_LOT", "REGRIND_BATCH", "TOOL", "PACKAGING_SPEC"}

# Polymorphic subject -> (store key, not-found error id)
SUBJECT_LOOKUP = {
    "MATERIAL_LOT": ("material_lots", "ERR_MATERIAL_LOT_NOT_FOUND"),
    "REGRIND_BATCH": ("regrind_batches", "ERR_REGRIND_BATCH_NOT_FOUND"),
    "TOOL": ("tools", "ERR_TOOL_NOT_FOUND"),
    "PACKAGING_SPEC": ("packaging_specs", "ERR_PACKAGING_SPEC_NOT_FOUND"),
}


@bp.route("/cleanliness-certificates", methods=["POST"])
@endpoint({"QualityInspector"})
def create_cert(user_id, role):
    body = body_dict(request.get_json(silent=True))
    subject_type = as_enum(req_present(body, "subject_type"), "subject_type", SUBJECT_TYPES)
    subject_id = as_string(req_present(body, "subject_id"), "subject_id")
    grade = as_enum(req_present(body, "grade"), "grade", GRADES)
    issued_at = parse_dt(req_present(body, "issued_at"), "issued_at")
    expires_at = parse_dt(req_present(body, "expires_at"), "expires_at")
    if expires_at <= issued_at:
        raise ApiError("ERR_INVALID_REQUEST", "expires_at must be later than issued_at")
    cert_body = as_string(req_present(body, "cert_body"), "cert_body")

    # p4 existence: polymorphic subject must exist as an entity of subject_type
    store_key, not_found = SUBJECT_LOOKUP[subject_type]
    subject = STORE[store_key].get(subject_id)
    if subject is None:
        raise ApiError(not_found, "%s %s does not exist" % (subject_type, subject_id))

    rec = new_record(common=False)
    rec.update({
        "subject_type": subject_type,
        "subject_id": subject_id,
        "grade": grade,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "cert_body": cert_body,
    })
    STORE["cleanliness_certificates"][rec["id"]] = rec

    # Side effect: release a QUARANTINE lot whose required grade is met by a
    # currently valid certificate (PRD §3.1)
    if subject_type == "MATERIAL_LOT" and subject["status"] == "QUARANTINE":
        if (
            GRADE_RANK[grade] >= GRADE_RANK[subject["cleanliness_grade_required"]]
            and cert_is_valid(rec)
        ):
            subject["status"] = "CERTIFIED"
            bump(subject)

    return ok_object(ser_cert(rec), 201)


@bp.route("/cleanliness-certificates", methods=["GET"])
@endpoint(ANY_ROLE)
def list_certs(user_id, role):
    items = list(STORE["cleanliness_certificates"].values())
    subject_type = request.args.get("subject_type")
    if subject_type is not None:
        items = [c for c in items if c["subject_type"] == subject_type]
    subject_id = request.args.get("subject_id")
    if subject_id is not None:
        items = [c for c in items if c["subject_id"] == subject_id]
    return list_response(items, ser_cert)


@bp.route("/cleanliness-certificates/<certId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_cert(user_id, role, certId):
    return ok_object(ser_cert(get_cert(certId)))
