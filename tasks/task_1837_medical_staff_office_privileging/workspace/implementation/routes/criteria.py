from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, is_int, paginate, require_fields

bp = Blueprint("criteria", __name__)

COORD = "MedicalStaffCoordinator"


@bp.route("/mso/specialty-criteria", methods=["POST"])
@require_roles(COORD)
def create_criteria():
    body = get_body()
    # Rung 11: input shape.
    require_fields(body, ["specialty_code", "privilege_line",
                          "min_training_months", "min_case_volume_24mo",
                          "required_board_cert", "fppe_case_count",
                          "volume_tier_table"])
    if not isinstance(body["specialty_code"], str) or not body["specialty_code"]:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "specialty_code must be a non-empty string")
    if not isinstance(body["privilege_line"], str) or not body["privilege_line"]:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "privilege_line must be a non-empty string")
    for f in ("min_training_months", "min_case_volume_24mo", "fppe_case_count"):
        if not is_int(body[f]) or body[f] < 0:
            errors.raise_err(errors.ERR_INVALID_REQUEST,
                             f"{f} must be a non-negative integer")
    if not isinstance(body["required_board_cert"], bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "required_board_cert must be a boolean")
    tiers = body["volume_tier_table"]
    if not isinstance(tiers, list):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "volume_tier_table must be an array")
    for t in tiers:
        if not isinstance(t, dict) or "tier_name" not in t or \
                "min_cases" not in t or "score_multiplier" not in t:
            errors.raise_err(
                errors.ERR_INVALID_REQUEST,
                "volume_tier_table rows must carry tier_name, min_cases, "
                "score_multiplier")
        if not is_int(t["min_cases"]):
            errors.raise_err(errors.ERR_INVALID_REQUEST,
                             "tier min_cases must be an integer")
        if not isinstance(t["score_multiplier"], (int, float)) \
                or isinstance(t["score_multiplier"], bool):
            errors.raise_err(errors.ERR_INVALID_REQUEST,
                             "tier score_multiplier must be numeric")
    # The row key is the (specialty_code, privilege_line) pair (PRD §3.1:
    # "keyed by a `specialty_code` ... together with a named `privilege_line`
    # within that specialty") — one specialty carries many privilege lines.
    for c in db.criteria.values():
        if c["specialty_code"] == body["specialty_code"] \
                and c["privilege_line"] == body["privilege_line"]:
            errors.raise_err(errors.ERR_INVALID_REQUEST,
                             "specialty_code + privilege_line must be unique")
    rec = services.base_record()
    rec.update({
        "specialty_code": body["specialty_code"],
        "privilege_line": body["privilege_line"],
        "min_training_months": body["min_training_months"],
        "min_case_volume_24mo": body["min_case_volume_24mo"],
        "required_board_cert": body["required_board_cert"],
        "fppe_case_count": body["fppe_case_count"],
        "volume_tier_table": tiers,
    })
    db.criteria[rec["id"]] = rec
    return ok_object(serializers.criterion(rec), 201)


@bp.route("/mso/specialty-criteria", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_criteria():
    items, limit, offset, total = paginate(
        db.criteria.values(), serializers.criterion,
        ["specialty_code", "privilege_line"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/specialty-criteria/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_criteria(cid):
    rec = db.criteria.get(cid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "SpecialtyCriteria not found")
    return ok_object(serializers.criterion(rec))
