"""StaffingMatrixRule endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_MATRIX_RULE_EXISTS
from middleware import require_roles
from response import success_object
from services.core import UNIT_TYPES, ACUITY_LEVELS, matrix_rule_for, pub
from util import get_json_body, req_enum, req_int

bp = Blueprint("matrix_rules", __name__)


@bp.post("/matrix-rules")
@require_roles("NurseAdmin")
def create_matrix_rule(_user_id: str, _role: str):
    body = get_json_body()
    unit_type = req_enum(body, "unit_type", UNIT_TYPES)
    acuity_level = req_enum(body, "acuity_level", ACUITY_LEVELS)
    patients_per_nurse = req_int(body, "patients_per_nurse")
    if patients_per_nurse < 1:
        raise_err(ERR_INVALID_REQUEST, "patients_per_nurse must be >= 1")

    if matrix_rule_for(unit_type, acuity_level) is not None:
        raise_err(ERR_MATRIX_RULE_EXISTS, "A matrix rule already exists for this unit_type/acuity_level pair")

    rule = {
        "unit_type": unit_type,
        "acuity_level": acuity_level,
        "patients_per_nurse": patients_per_nurse,
    }
    db.stamp_new(rule)
    db.matrix_rules[rule["id"]] = rule
    return success_object(pub(rule), 201)
