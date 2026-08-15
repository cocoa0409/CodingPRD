"""AnnualStatement lifecycle: generate, finalize, deliver, acknowledge,
dispute, regenerate."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import (ApiError, ERR_INVALID_STATE, ERR_TRUST_NOT_ACTIVE,
                    ERR_RESOURCE_NOT_FOUND, ERR_NOT_OWN_RESOURCE,
                    ERR_STATEMENT_YEAR_EXISTS, ERR_OBJECTION_WINDOW_EXPIRED)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import statement_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("statements", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "TrustOperationsOfficer"}
GET_ROLES = READ_ROLES | {"Beneficiary"}
OBJECTION_WINDOW_DAYS = 30


def _compute_and_store(s, trust):
    s.update(calc.statement_totals(trust, s["fiscal_year"]))


def _check_beneficiary_of_trust(user_id, trust_id):
    b = db.beneficiaries.get(user_id)
    if b is None or b["trust_id"] != trust_id or b["status"] != "ACTIVE":
        raise ApiError(ERR_NOT_OWN_RESOURCE, 403,
                       "Caller is not an ACTIVE beneficiary of this trust")


@bp.route("/trusts/annual-statements", methods=["POST"])
def create_statement():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("fiscal_year", "int", True),
    ])
    require_role(role, {"TrustOfficer"})
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    if trust["status"] not in ("ACTIVE", "SUSPENDED", "TERMINATING", "TERMINATED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust status does not permit statement generation")
    # [8] one non-SUPERSEDED statement per (trust, fiscal_year)
    for s in db.statements.values():
        if (s["trust_id"] == trust["id"] and s["fiscal_year"] == v["fiscal_year"]
                and s["status"] != "SUPERSEDED"):
            raise ApiError(ERR_STATEMENT_YEAR_EXISTS, 409,
                           "A statement already exists for this fiscal year")
    s = workflow.new_entity()
    s.update({
        "trust_id": trust["id"],
        "fiscal_year": v["fiscal_year"],
        "status": "DRAFT",
        "delivered_at": None,
        "acknowledged_at": None,
        "dispute_reason": None,
    })
    _compute_and_store(s, trust)
    db.statements[s["id"]] = s
    return ok(statement_json(s), status=201)


@bp.route("/trusts/annual-statements", methods=["GET"])
def list_statements():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    fy = request.args.get("fiscal_year")
    if fy is not None:
        try:
            filters.append(("fiscal_year", int(fy)))
        except ValueError:
            filters.append(("fiscal_year", None))
    items, total = workflow.list_page(db.statements, filters, statement_json,
                                      limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/annual-statements/<sid>", methods=["GET"])
def get_statement(sid):
    user_id, role = authenticate()
    require_role(role, GET_ROLES)
    s = find_or_404(db.statements, sid, "AnnualStatement")
    if role == "Beneficiary":
        _check_beneficiary_of_trust(user_id, s["trust_id"])
    return ok(statement_json(s))


@bp.route("/trusts/annual-statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    s = find_or_404(db.statements, sid, "AnnualStatement")
    if s["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Statement must be DRAFT to finalize")
    s["status"] = "FINALIZED"
    workflow.touch(s)
    return ok(statement_json(s))


@bp.route("/trusts/annual-statements/<sid>/deliver", methods=["POST"])
def deliver_statement(sid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    s = find_or_404(db.statements, sid, "AnnualStatement")
    if s["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Statement must be FINALIZED to deliver")
    s["status"] = "DELIVERED"
    s["delivered_at"] = workflow.now_stamp()
    workflow.touch(s)
    return ok(statement_json(s))


@bp.route("/trusts/annual-statements/<sid>/acknowledge", methods=["POST"])
def acknowledge_statement(sid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"Beneficiary"})
    s = find_or_404(db.statements, sid, "AnnualStatement")
    _check_beneficiary_of_trust(user_id, s["trust_id"])
    if s["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Statement must be DELIVERED to acknowledge")
    s["status"] = "ACKNOWLEDGED"
    s["acknowledged_at"] = workflow.now_stamp()
    workflow.touch(s)
    return ok(statement_json(s))


@bp.route("/trusts/annual-statements/<sid>/dispute", methods=["POST"])
def dispute_statement(sid):
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [("dispute_reason", "str", True)])
    require_role(role, {"Beneficiary"})
    s = find_or_404(db.statements, sid, "AnnualStatement")
    _check_beneficiary_of_trust(user_id, s["trust_id"])
    if s["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Statement must be DELIVERED to dispute")
    deadline = clock.parse_dt(s["delivered_at"]) + timedelta(days=OBJECTION_WINDOW_DAYS)
    if clock.now_dt() > deadline:
        raise ApiError(ERR_OBJECTION_WINDOW_EXPIRED, 422,
                       "Objection window has expired")
    s["status"] = "DISPUTED"
    s["dispute_reason"] = v["dispute_reason"]
    workflow.touch(s)
    return ok(statement_json(s))


@bp.route("/trusts/annual-statements/<sid>/regenerate", methods=["POST"])
def regenerate_statement(sid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    s = find_or_404(db.statements, sid, "AnnualStatement")
    if s["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Statement must be DISPUTED to regenerate")
    trust = db.trusts.get(s["trust_id"])
    _compute_and_store(s, trust)
    s["status"] = "DRAFT"
    s["delivered_at"] = None
    s["dispute_reason"] = None
    workflow.touch(s)
    return ok(statement_json(s))
