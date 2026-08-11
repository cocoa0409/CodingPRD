"""Claim endpoints: filing, register browsing, review/allow/reopen/withdraw,
objection creation, and claim-scoped sub-listings."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_NOT_ASSIGNED_TRUSTEE, ERR_REFERENTIAL_INTEGRITY,
    ERR_OBJECTION_ALREADY_PENDING, ERR_CASE_BEYOND_REOPEN, ERR_DIVIDEND_POSTED,
    ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_calc import register_claim_number
from services_common import (
    new_entity, touch, bump_case, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, posted_dividend_for_claim, claim_late,
    ser_claim, ser_objection, ser_asset, ser_dividend, sorted_rows,
    PRIORITY_CLASSES,
)
from util import parse_datetime, require_str, require_int, require_enum

bp = Blueprint("claims", __name__)

OBJECTION_GROUNDS = (
    "DUPLICATE", "INSUFFICIENT_DOCUMENTATION", "AMOUNT_DISPUTED",
    "WRONG_CLASS", "LATE_FILED", "NOT_OWED",
)


def _get_claim_and_case(claim_id):
    claim = get_or_404(db.claims, claim_id, "claim")
    return claim, db.cases[claim["case_id"]]


@bp.route("/trustee/cases/<id>/claims", methods=["POST"])
def file_claim(id):
    uid, role = auth_context()
    require_roles(role, ("Creditor", "Clerk"))
    case = get_case(id)
    ensure_case_open(case)
    body = json_body()

    # Tier 6 identity binding (evaluable only when creditor_id is present).
    raw_creditor = body.get("creditor_id")
    if role == "Creditor" and isinstance(raw_creditor, str):
        if uid != raw_creditor:
            raise ApiError(ERR_NOT_ASSIGNED_TRUSTEE, 403, "A creditor may file only its own claim.")

    # Tier 8 referential integrity.
    if isinstance(raw_creditor, str) and raw_creditor not in db.creditors:
        raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422, "creditor_id does not reference an existing creditor.")
    raw_asset = body.get("secured_by_asset_id")
    if isinstance(raw_asset, str):
        asset = db.assets.get(raw_asset)
        if asset is None or asset["case_id"] != id:
            raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                           "secured_by_asset_id must name an asset of this case.")

    # Tier 13 body shape.
    creditor_id = require_str(body, "creditor_id")
    received_at = parse_datetime(body.get("received_at"), "received_at")
    filed_amount = require_int(body, "filed_amount_cents", minimum=0)
    priority_class = require_enum(body, "priority_class", PRIORITY_CLASSES)
    secured_by = body.get("secured_by_asset_id")
    if secured_by is not None and not isinstance(secured_by, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "secured_by_asset_id must be a string.")
    if priority_class == "SECURED" and not secured_by:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "secured_by_asset_id is required when priority_class is SECURED.")

    claim = new_entity({
        "case_id": id,
        "creditor_id": creditor_id,
        "claim_number": 0,
        "received_at": received_at,
        "filed_amount_cents": filed_amount,
        "allowed_amount_cents": 0,
        "priority_class": priority_class,
        "secured_by_asset_id": secured_by,
        "reclassified_from_claim_id": None,
        "status": "FILED",
        "objection_id": None,
    })
    db.claims[claim["id"]] = claim
    register_claim_number(claim)
    return ok_object(ser_claim(claim), status=201)


@bp.route("/trustee/cases/<id>/claims", methods=["GET"])
def list_case_claims(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    case = get_case(id)
    status = request.args.get("status")
    priority_class = request.args.get("priority_class")
    late = request.args.get("late")
    creditor_id = request.args.get("creditor_id")
    rows = [c for c in db.claims.values() if c["case_id"] == id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if priority_class is not None:
        rows = [c for c in rows if c["priority_class"] == priority_class]
    if creditor_id is not None:
        rows = [c for c in rows if c["creditor_id"] == creditor_id]
    if late is not None:
        if late.lower() == "true":
            rows = [c for c in rows if claim_late(c, case)]
        elif late.lower() == "false":
            rows = [c for c in rows if not claim_late(c, case)]
    return paginate([ser_claim(c) for c in sorted_rows(rows)])


@bp.route("/trustee/claims", methods=["GET"])
def list_claims():
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    creditor_id = request.args.get("creditor_id")
    secured_by = request.args.get("secured_by_asset_id")
    objection_id = request.args.get("objection_id")
    reclassified = request.args.get("reclassified_from_claim_id")
    rows = list(db.claims.values())
    if creditor_id is not None:
        rows = [c for c in rows if c["creditor_id"] == creditor_id]
    if secured_by is not None:
        rows = [c for c in rows if c["secured_by_asset_id"] == secured_by]
    if objection_id is not None:
        rows = [c for c in rows if c["objection_id"] == objection_id]
    if reclassified is not None:
        rows = [c for c in rows if c["reclassified_from_claim_id"] == reclassified]
    return paginate([ser_claim(c) for c in sorted_rows(rows)])


@bp.route("/trustee/claims/<id>", methods=["GET"])
def get_claim(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_claim(get_or_404(db.claims, id, "claim")))


@bp.route("/trustee/claims/<id>/dividends", methods=["GET"])
def claim_dividends(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.claims, id, "claim")
    rows = [d for d in db.dividends.values() if d["claim_id"] == id]
    return paginate([ser_dividend(d) for d in sorted_rows(rows)])


@bp.route("/trustee/claims/<id>/objections", methods=["GET"])
def claim_objections(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.claims, id, "claim")
    rows = [o for o in db.objections.values() if o["claim_id"] == id]
    return paginate([ser_objection(o) for o in sorted_rows(rows)])


@bp.route("/trustee/claims/<id>/encumbered_assets", methods=["GET"])
def claim_encumbered_assets(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    claim = get_or_404(db.claims, id, "claim")
    rows = [a for a in db.assets.values() if a["encumbered_claim_id"] == id]
    securing = db.assets.get(claim["secured_by_asset_id"]) if claim["secured_by_asset_id"] else None
    if securing is not None and all(a["id"] != securing["id"] for a in rows):
        rows.append(securing)
    return paginate([ser_asset(a) for a in sorted_rows(rows)])


@bp.route("/trustee/claims/<id>/review", methods=["POST"])
def review_claim(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    claim, case = _get_claim_and_case(id)
    ensure_case_open(case)
    if claim["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be FILED to begin review.")
    ensure_trustee_binding(case, uid)
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok_object(ser_claim(claim))


@bp.route("/trustee/claims/<id>/allow", methods=["POST"])
def allow_claim(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    claim, case = _get_claim_and_case(id)
    ensure_case_open(case)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be UNDER_REVIEW to allow.")
    ensure_trustee_binding(case, uid)
    claim["allowed_amount_cents"] = claim["filed_amount_cents"]
    claim["status"] = "ALLOWED"
    case["allowed_claims_total_cents"] += claim["allowed_amount_cents"]
    touch(claim)
    bump_case(case)
    return ok_object(ser_claim(claim))


@bp.route("/trustee/claims/<id>/reopen", methods=["POST"])
def reopen_claim(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    claim, case = _get_claim_and_case(id)
    ensure_case_open(case)
    if claim["status"] != "ALLOWED":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be ALLOWED to reopen.")
    ensure_trustee_binding(case, uid)
    if case["status"] not in ("CLAIMS_ADMINISTRATION", "LIQUIDATION"):
        raise ApiError(ERR_CASE_BEYOND_REOPEN, 409,
                       "The register is fixed once the case reaches DISTRIBUTION.")
    if posted_dividend_for_claim(id) is not None:
        raise ApiError(ERR_DIVIDEND_POSTED, 409, "A POSTED dividend references this claim.")
    case["allowed_claims_total_cents"] -= claim["allowed_amount_cents"]
    claim["allowed_amount_cents"] = 0
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    bump_case(case)
    return ok_object(ser_claim(claim))


@bp.route("/trustee/claims/<id>/withdraw", methods=["POST"])
def withdraw_claim(id):
    uid, role = auth_context()
    require_roles(role, ("Creditor",))
    claim, case = _get_claim_and_case(id)
    ensure_case_open(case)
    if claim["status"] not in ("FILED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a FILED or UNDER_REVIEW claim may be withdrawn.")
    if uid != claim["creditor_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TRUSTEE, 403, "A creditor may withdraw only its own claim.")
    if claim["status"] == "FILED" and posted_dividend_for_claim(id) is not None:
        raise ApiError(ERR_DIVIDEND_POSTED, 409, "A POSTED dividend references this claim.")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return ok_object(ser_claim(claim))


@bp.route("/trustee/claims/<id>/objections", methods=["POST"])
def create_objection(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    claim, case = _get_claim_and_case(id)
    ensure_case_open(case)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Claim must be UNDER_REVIEW to object.")
    ensure_trustee_binding(case, uid)
    if any(o["claim_id"] == id and o["status"] == "PENDING" for o in db.objections.values()):
        raise ApiError(ERR_OBJECTION_ALREADY_PENDING, 409,
                       "An objection is already PENDING against this claim.")
    body = json_body()
    grounds = require_enum(body, "grounds", OBJECTION_GROUNDS)
    proposed_amount = require_int(body, "proposed_allowed_amount_cents", minimum=0)
    proposed_class = require_enum(body, "proposed_priority_class", PRIORITY_CLASSES)
    if grounds != "WRONG_CLASS" and proposed_class != claim["priority_class"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "proposed_priority_class must equal the claim's class unless grounds is WRONG_CLASS.")

    objection = new_entity({
        "case_id": claim["case_id"],
        "claim_id": id,
        "grounds": grounds,
        "proposed_allowed_amount_cents": proposed_amount,
        "proposed_priority_class": proposed_class,
        "status": "PENDING",
        "resolved_at": None,
    })
    db.objections[objection["id"]] = objection
    claim["status"] = "OBJECTED"
    claim["objection_id"] = objection["id"]
    touch(claim)
    bump_case(case)
    return ok_object(ser_objection(objection), status=201)
