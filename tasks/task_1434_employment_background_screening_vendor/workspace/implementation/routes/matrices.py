"""AdjudicationMatrix endpoints."""
from flask import Blueprint

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_MATRIX_NOT_DRAFT, ERR_MATRIX_ALREADY_ACTIVE,
    ERR_MATRIX_NOT_ACTIVE,
)
from middleware import (
    auth, require_role, get_body, req_enum, invalid, ALL_ROLES,
)
from response import success_object

bp = Blueprint("matrices", __name__)

RISK_TIERS = ("TIER_1_STANDARD", "TIER_2_ELEVATED", "TIER_3_HIGH_RISK")
OFFENSE_CATEGORIES = (
    "VIOLENT_FELONY", "NONVIOLENT_FELONY", "MISDEMEANOR", "INFRACTION",
    "ARREST_NO_CONVICTION", "EMPLOYMENT_DISCREPANCY",
    "EDUCATION_DISCREPANCY", "SANCTIONS_HIT",
)
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
ACTIONS = ("CLEAR", "IA_REQUIRED", "ADVERSE_ELIGIBLE")


def _validate_rules(value):
    if not isinstance(value, list) or len(value) < 1:
        invalid("rules must be a non-empty array")
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            invalid("each rule must be an object")
        cat = entry.get("offense_category")
        if not isinstance(cat, str) or cat not in OFFENSE_CATEGORIES:
            invalid("rule offense_category invalid")
        sev = entry.get("min_severity")
        if not isinstance(sev, str) or sev not in SEVERITIES:
            invalid("rule min_severity invalid")
        recency = entry.get("max_recency_years")
        if isinstance(recency, bool) or not isinstance(recency, int) or recency < 0:
            invalid("rule max_recency_years invalid")
        action = entry.get("action")
        if not isinstance(action, str) or action not in ACTIONS:
            invalid("rule action invalid")
        cleaned.append({
            "offense_category": cat,
            "min_severity": sev,
            "max_recency_years": recency,
            "action": action,
        })
    return cleaned


@bp.route("/adjudication-matrices", methods=["POST"])
def create_matrix():
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()
    risk_tier = req_enum(body, "risk_tier", RISK_TIERS)
    rules = _validate_rules(body.get("rules"))
    matrix = db.new_entity({
        "risk_tier": risk_tier,
        "rules": rules,
        "status": "DRAFT",
    })
    db.matrices[matrix["id"]] = matrix
    return success_object(matrix, 201)


def _load_matrix(matrix_id):
    matrix = db.matrices.get(matrix_id)
    if matrix is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Matrix not found")
    return matrix


@bp.route("/adjudication-matrices/<matrix_id>", methods=["GET"])
def get_matrix(matrix_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_matrix(matrix_id), 200)


@bp.route("/adjudication-matrices/<matrix_id>/activate", methods=["POST"])
def activate_matrix(matrix_id):
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    matrix = _load_matrix(matrix_id)
    if matrix["status"] != "DRAFT":
        raise ApiError(ERR_MATRIX_NOT_DRAFT, 409,
                       "Activate requires matrix DRAFT")
    for other in db.matrices.values():
        if (other["id"] != matrix["id"]
                and other["risk_tier"] == matrix["risk_tier"]
                and other["status"] == "ACTIVE"):
            raise ApiError(ERR_MATRIX_ALREADY_ACTIVE, 409,
                           "Another ACTIVE matrix exists for this risk_tier")
    matrix["status"] = "ACTIVE"
    bump(matrix)
    return success_object(matrix, 200)


@bp.route("/adjudication-matrices/<matrix_id>/retire", methods=["POST"])
def retire_matrix(matrix_id):
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    matrix = _load_matrix(matrix_id)
    if matrix["status"] != "ACTIVE":
        raise ApiError(ERR_MATRIX_NOT_ACTIVE, 409,
                       "Retire requires matrix ACTIVE")
    matrix["status"] = "RETIRED"
    bump(matrix)
    return success_object(matrix, 200)
