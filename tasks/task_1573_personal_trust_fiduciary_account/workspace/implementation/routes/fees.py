"""FeeAssessment workflow: calculate, disclose, post, dispute, recalculate, reverse."""

from datetime import date, timedelta

from flask import Blueprint, request

import clock
import db
import serialize
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_TRUST_NOT_ACTIVE, ERR_RESOURCE_NOT_FOUND,
                    ERR_NOT_OWN_RESOURCE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_FEE_PERIOD_NOT_CONTIGUOUS, ERR_OBJECTION_WINDOW_EXPIRED,
                    ERR_FEE_EXCEEDS_AVAILABLE_BALANCE)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import fee_assessment_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("fees", __name__)

VARIANTS = {"PROVISIONAL", "FINAL"}
READ_ROLES = {"TrustOfficer", "TrustExecutive", "TrustOperationsOfficer"}
GET_ROLES = READ_ROLES | {"Beneficiary"}
OBJECTION_WINDOW_DAYS = 30


def _compute_and_store(f):
    base = calc.fee_base(f["trust_id"], f["variant"], f["period_end"])
    f.update(calc.compute_fee_amounts(base))


def _check_beneficiary_of_trust(user_id, trust_id):
    """Objection ownership: X-User-ID must be an ACTIVE Beneficiary of the trust."""
    b = db.beneficiaries.get(user_id)
    if b is None or b["trust_id"] != trust_id or b["status"] != "ACTIVE":
        raise ApiError(ERR_NOT_OWN_RESOURCE, 403,
                       "Caller is not an ACTIVE beneficiary of this trust")


@bp.route("/trusts/fee-assessments", methods=["POST"])
def create_fee():
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("period_start", "date", True),
        ("period_end", "date", True),
        ("variant", "str", True, VARIANTS),
    ])
    if date.fromisoformat(v["period_start"]) > date.fromisoformat(v["period_end"]):
        raise ApiError(ERR_VALIDATION, 400,
                       "period_start must be on or before period_end")
    require_role(role, {"TrustOperationsOfficer"})
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    if trust["status"] not in ("ACTIVE", "TERMINATING"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE or TERMINATING to assess fees")
    # [8] FINAL periods tile gap-free: start == latest non-REVERSED FINAL end + 1 day
    if v["variant"] == "FINAL":
        prior_ends = [
            date.fromisoformat(f["period_end"])
            for f in db.fee_assessments.values()
            if f["trust_id"] == trust["id"] and f["variant"] == "FINAL"
            and f["status"] != "REVERSED"
        ]
        if prior_ends:
            expected = max(prior_ends) + timedelta(days=1)
            if date.fromisoformat(v["period_start"]) != expected:
                raise ApiError(ERR_FEE_PERIOD_NOT_CONTIGUOUS, 409,
                               "FINAL period_start must equal prior FINAL "
                               "period_end + 1 day")
    f = workflow.new_entity()
    f.update({
        "trust_id": trust["id"],
        "period_start": v["period_start"],
        "period_end": v["period_end"],
        "variant": v["variant"],
        "status": "CALCULATED",
        "calculated_by_user_id": user_id,
        "disclosed_by_user_id": None,
        "posted_by_user_id": None,
        "disclosed_at": None,
        "dispute_reason": None,
    })
    _compute_and_store(f)
    db.fee_assessments[f["id"]] = f
    return ok(fee_assessment_json(f), status=201)


@bp.route("/trusts/fee-assessments", methods=["GET"])
def list_fees():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.fee_assessments, filters,
                                      fee_assessment_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/fee-assessments/<fid>", methods=["GET"])
def get_fee(fid):
    user_id, role = authenticate()
    require_role(role, GET_ROLES)
    f = find_or_404(db.fee_assessments, fid, "FeeAssessment")
    if role == "Beneficiary":
        _check_beneficiary_of_trust(user_id, f["trust_id"])
    return ok(fee_assessment_json(f))


@bp.route("/trusts/fee-assessments/<fid>/disclose", methods=["POST"])
def disclose(fid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"TrustOperationsOfficer"})
    f = find_or_404(db.fee_assessments, fid, "FeeAssessment")
    if f["status"] != "CALCULATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee must be CALCULATED to disclose")
    f["status"] = "DISCLOSED"
    f["disclosed_by_user_id"] = user_id
    f["disclosed_at"] = workflow.now_stamp()
    workflow.touch(f)
    return ok(fee_assessment_json(f))


@bp.route("/trusts/fee-assessments/<fid>/post", methods=["POST"])
def post_fee(fid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"TrustOperationsOfficer"})
    f = find_or_404(db.fee_assessments, fid, "FeeAssessment")
    # [4] segregation of duties: poster must differ from discloser
    if f["disclosed_by_user_id"] is not None and user_id == f["disclosed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Poster must differ from the discloser")
    if f["status"] != "DISCLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee must be DISCLOSED to post")
    # [11] funds check last
    trust = db.trusts.get(f["trust_id"])
    avail_i = (serialize.income_balance(f["trust_id"])
               - serialize.reserved_income(f["trust_id"]))
    avail_p = (serialize.principal_balance(f["trust_id"])
               - serialize.reserved_principal(f["trust_id"]))
    if f["income_portion_cents"] > avail_i or f["principal_portion_cents"] > avail_p:
        raise ApiError(ERR_FEE_EXCEEDS_AVAILABLE_BALANCE, 422,
                       "Fee portions exceed available balances")
    value_date = clock.now_date().isoformat()
    workflow.append_ledger(
        f["trust_id"], "FEE", "INCOME", -f["income_portion_cents"], value_date,
        source_entity_type="FEE_ASSESSMENT", source_entity_id=f["id"])
    workflow.append_ledger(
        f["trust_id"], "FEE", "PRINCIPAL", -f["principal_portion_cents"], value_date,
        source_entity_type="FEE_ASSESSMENT", source_entity_id=f["id"])
    f["status"] = "POSTED"
    f["posted_by_user_id"] = user_id
    workflow.touch(f)
    if trust is not None:
        workflow.bump_trust(trust)
    return ok(fee_assessment_json(f))


@bp.route("/trusts/fee-assessments/<fid>/dispute", methods=["POST"])
def dispute_fee(fid):
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [("dispute_reason", "str", True)])
    require_role(role, {"Beneficiary"})
    f = find_or_404(db.fee_assessments, fid, "FeeAssessment")
    # [4] ownership
    _check_beneficiary_of_trust(user_id, f["trust_id"])
    # [6] state
    if f["status"] != "DISCLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee must be DISCLOSED to dispute")
    # [8] objection window: clock <= disclosed_at + 30 days, inclusive
    deadline = clock.parse_dt(f["disclosed_at"]) + timedelta(days=OBJECTION_WINDOW_DAYS)
    if clock.now_dt() > deadline:
        raise ApiError(ERR_OBJECTION_WINDOW_EXPIRED, 422,
                       "Objection window has expired")
    f["status"] = "DISPUTED"
    f["dispute_reason"] = v["dispute_reason"]
    workflow.touch(f)
    return ok(fee_assessment_json(f))


@bp.route("/trusts/fee-assessments/<fid>/recalculate", methods=["POST"])
def recalculate_fee(fid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOperationsOfficer"})
    f = find_or_404(db.fee_assessments, fid, "FeeAssessment")
    if f["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee must be DISPUTED to recalculate")
    _compute_and_store(f)
    f["status"] = "CALCULATED"
    f["disclosed_by_user_id"] = None
    f["disclosed_at"] = None
    workflow.touch(f)
    return ok(fee_assessment_json(f))


@bp.route("/trusts/fee-assessments/<fid>/reverse", methods=["POST"])
def reverse_fee(fid):
    _, role = authenticate()
    data = get_body()
    validate(data, [("reason", "str", True)])
    require_role(role, {"TrustExecutive"})
    f = find_or_404(db.fee_assessments, fid, "FeeAssessment")
    if f["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee must be POSTED to reverse")
    value_date = clock.now_date().isoformat()
    workflow.append_ledger(
        f["trust_id"], "ADJUSTMENT", "INCOME", f["income_portion_cents"], value_date,
        source_entity_type="FEE_ASSESSMENT", source_entity_id=f["id"])
    workflow.append_ledger(
        f["trust_id"], "ADJUSTMENT", "PRINCIPAL", f["principal_portion_cents"],
        value_date, source_entity_type="FEE_ASSESSMENT", source_entity_id=f["id"])
    f["status"] = "REVERSED"
    workflow.touch(f)
    trust = db.trusts.get(f["trust_id"])
    if trust is not None:
        workflow.bump_trust(trust)
    return ok(fee_assessment_json(f))
