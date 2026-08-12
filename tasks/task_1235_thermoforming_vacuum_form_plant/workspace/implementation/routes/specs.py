"""PackagingSpec endpoints (PRD §3.4)."""

from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_spec
from services import get_spec, valid_cert_at_grade
from util import (
    GRADES,
    as_enum,
    as_nonnegative_decimal,
    as_string,
    body_dict,
    req_present,
)

from routes import bp

SPEC_TYPES = {"STOCK", "CUSTOM"}


@bp.route("/packaging-specs", methods=["POST"])
@endpoint({"PackagingEngineer"})
def create_spec(user_id, role):
    body = body_dict(request.get_json(silent=True))
    spec_code = as_string(req_present(body, "spec_code"), "spec_code")
    spec_type = as_enum(req_present(body, "spec_type"), "spec_type", SPEC_TYPES)
    grade = as_enum(req_present(body, "cleanliness_grade"), "cleanliness_grade", GRADES)
    per_pack_cost = as_nonnegative_decimal(req_present(body, "per_pack_cost"), "per_pack_cost")

    rec = new_record()
    rec.update({
        "spec_code": spec_code,
        "spec_type": spec_type,
        "cleanliness_grade": grade,
        "per_pack_cost": per_pack_cost,
        "decided_by_user_id": None,
        "status": "ACTIVE" if spec_type == "STOCK" else "PENDING_APPROVAL",
    })
    STORE["packaging_specs"][rec["id"]] = rec
    return ok_object(ser_spec(rec), 201)


@bp.route("/packaging-specs", methods=["GET"])
@endpoint(ANY_ROLE)
def list_specs(user_id, role):
    items = list(STORE["packaging_specs"].values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    spec_type = request.args.get("spec_type")
    if spec_type is not None:
        items = [s for s in items if s["spec_type"] == spec_type]
    return list_response(items, ser_spec)


@bp.route("/packaging-specs/<specId>/decide", methods=["POST"])
@endpoint({"PlantManager"})
def decide_spec(user_id, role, specId):
    body = body_dict(request.get_json(silent=True))
    decision = as_enum(req_present(body, "decision"), "decision", {"APPROVED", "REJECTED"})

    spec = get_spec(specId)
    if spec["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_SPEC_STATE", "Spec decide requires status PENDING_APPROVAL")
    if decision == "APPROVED":
        # Certificate gate: currently valid PACKAGING_SPEC cert at sufficient grade
        if not valid_cert_at_grade("PACKAGING_SPEC", spec["id"], spec["cleanliness_grade"]):
            raise ApiError(
                "ERR_CERTIFICATE_INVALID",
                "No currently valid cleanliness certificate at the spec's grade",
            )
    spec["status"] = decision  # APPROVED or REJECTED
    spec["decided_by_user_id"] = user_id
    bump(spec)
    return ok_object(ser_spec(spec))
