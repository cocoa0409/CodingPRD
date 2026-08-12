"""ClaimObjection resolution endpoints: sustain / overrule / settle / withdraw."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_SETTLEMENT_NOT_PARTIAL, ERR_INVALID_REQUEST,
)
from logical_clock import CLOCK
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_common import (
    touch, bump_case, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, ser_objection, sorted_rows, PRIORITY_CLASSES,
)
from util import require_enum, optional_enum

bp = Blueprint("objections", __name__)


def _get_objection_case_claim(objection_id):
    objection = get_or_404(db.objections, objection_id, "objection")
    case = db.cases[objection["case_id"]]
    claim = db.claims[objection["claim_id"]]
    return objection, case, claim


@bp.route("/trustee/cases/<id>/objections", methods=["GET"])
def list_case_objections(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    claim_id = request.args.get("claim_id")
    rows = [o for o in db.objections.values() if o["case_id"] == id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    if claim_id is not None:
        rows = [o for o in rows if o["claim_id"] == claim_id]
    return paginate([ser_objection(o) for o in sorted_rows(rows)])


@bp.route("/trustee/objections/<id>", methods=["GET"])
def get_objection(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_objection(get_or_404(db.objections, id, "objection")))


@bp.route("/trustee/objections/<id>/sustain", methods=["POST"])
def sustain_objection(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    objection, case, claim = _get_objection_case_claim(id)
    ensure_case_open(case)
    if objection["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Objection must be PENDING to sustain.")
    if claim["status"] != "OBJECTED" or claim["objection_id"] != objection["id"]:
        raise ApiError(ERR_INVALID_STATE, 409, "The claim is not under this objection.")
    objection["status"] = "SUSTAINED"
    objection["resolved_at"] = CLOCK.now()
    claim["status"] = "DISALLOWED"
    claim["allowed_amount_cents"] = 0
    claim["objection_id"] = None
    touch(objection)
    touch(claim)
    bump_case(case)
    return ok_object(ser_objection(objection))


@bp.route("/trustee/objections/<id>/overrule", methods=["POST"])
def overrule_objection(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    objection, case, claim = _get_objection_case_claim(id)
    ensure_case_open(case)
    if objection["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Objection must be PENDING to overrule.")
    claim["status"] = "ALLOWED"
    claim["allowed_amount_cents"] = claim["filed_amount_cents"]
    claim["objection_id"] = None
    case["allowed_claims_total_cents"] += claim["allowed_amount_cents"]
    objection["status"] = "OVERRULED"
    objection["resolved_at"] = CLOCK.now()
    touch(objection)
    touch(claim)
    bump_case(case)
    return ok_object(ser_objection(objection))


@bp.route("/trustee/objections/<id>/settle", methods=["POST"])
def settle_objection(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    objection, case, claim = _get_objection_case_claim(id)
    ensure_case_open(case)
    if objection["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Objection must be PENDING to settle.")
    ensure_trustee_binding(case, uid)
    body = json_body()
    outcome = require_enum(body, "outcome", ("ALLOW", "DISALLOW", "PARTIAL"))

    if outcome == "PARTIAL":
        settled_amount = body.get("settled_amount_cents")
        if isinstance(settled_amount, bool) or not isinstance(settled_amount, int):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "settled_amount_cents is required for a PARTIAL settlement.")
        if settled_amount < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "settled_amount_cents must be non-negative.")
        if settled_amount >= claim["filed_amount_cents"]:
            raise ApiError(ERR_SETTLEMENT_NOT_PARTIAL, 422,
                           "A PARTIAL settlement must be strictly below the filed amount.")
        settled_class = optional_enum(body, "settled_priority_class", PRIORITY_CLASSES)
        claim["status"] = "ALLOWED"
        claim["allowed_amount_cents"] = settled_amount
        claim["priority_class"] = settled_class if settled_class is not None else claim["priority_class"]
        case["allowed_claims_total_cents"] += settled_amount
    elif outcome == "ALLOW":
        claim["status"] = "ALLOWED"
        claim["allowed_amount_cents"] = claim["filed_amount_cents"]
        case["allowed_claims_total_cents"] += claim["allowed_amount_cents"]
    else:  # DISALLOW
        claim["status"] = "DISALLOWED"
        claim["allowed_amount_cents"] = 0

    claim["objection_id"] = None
    objection["status"] = "SETTLED"
    objection["resolved_at"] = CLOCK.now()
    touch(objection)
    touch(claim)
    bump_case(case)
    return ok_object(ser_objection(objection))


@bp.route("/trustee/objections/<id>/withdraw", methods=["POST"])
def withdraw_objection(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    objection, case, claim = _get_objection_case_claim(id)
    ensure_case_open(case)
    if objection["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Objection must be PENDING to withdraw.")
    ensure_trustee_binding(case, uid)
    objection["status"] = "WITHDRAWN"
    objection["resolved_at"] = CLOCK.now()
    claim["status"] = "UNDER_REVIEW"
    claim["objection_id"] = None
    touch(objection)
    touch(claim)
    bump_case(case)
    return ok_object(ser_objection(objection))
