from flask import Blueprint, request

from errors import ERR_NOT_FOUND, ERR_NURSE_NOT_FOUND, ERR_STALE_VERSION, ApiError
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, get_or_404, serialize, touch
from services.derived import append_evaluation, derive_privilege, recompute_posture

bp = Blueprint("evals", __name__)

CREATE_SCHEMA = {
    "nurse_id": ("string", True, None),
    "expected_nurse_version": ("int", True, None),
}


@bp.route("/credentialing/privilege-evaluations", methods=["POST"])
def create_evaluation():
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    if body["expected_nurse_version"] != nurse["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_nurse_version does not match the nurse's current version", 412)
    # The explicit evaluation always appends its MANUAL row, updates the nurse's
    # privilege fields, increments the nurse version by exactly 1, and recomputes
    # posture.
    _, status, scope, home_id = derive_privilege(nurse, reason=None)  # applies field changes
    evaluation = append_evaluation(nurse, "MANUAL", status, scope, home_id)
    recompute_posture(nurse, touch_nurse=False)
    touch(nurse)
    return success_object(serialize("evaluations", evaluation), 201)


@bp.route("/credentialing/privilege-evaluations", methods=["GET"])
def list_evaluations():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("evaluations")
    value = request.args.get("nurse_id")
    if value is not None:
        rows = [e for e in rows if e["nurse_id"] == value]
    total = len(rows)
    return success_list([serialize("evaluations", e) for e in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/privilege-evaluations/<evalId>", methods=["GET"])
def get_evaluation(evalId):
    auth_context()
    evaluation = get_or_404("evaluations", evalId, ERR_NOT_FOUND, "Privilege evaluation not found")
    return success_object(serialize("evaluations", evaluation))
