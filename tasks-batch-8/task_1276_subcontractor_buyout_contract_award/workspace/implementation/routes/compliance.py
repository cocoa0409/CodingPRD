"""InsuranceCertificate and BondDecision endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import STANDARD_READ_ROLES, auth
from response import ok, ok_list
from services import (
    EVALUATION_BASES,
    TRADE_HISTORIES,
    WORKERS_COMP_KINDS,
    bond_decision_for,
    bond_premium,
    certs_of,
    ensure_sub_not_terminal,
    evaluate_certificate,
    get_project,
    get_subcontract,
    package_of,
    recompute_insurance_status,
    ser_bond,
    ser_cert,
    sorted_created,
    stamp,
    touch,
    trade_risk_score,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    body,
    pagination_args,
    parse_ymd,
    required,
)

bp = Blueprint("compliance", __name__)


@bp.post("/subcontracts/<sub_id>/insurance-certificates")
def create_certificate(sub_id):
    auth(["BuyoutLead"])
    sub = get_subcontract(sub_id)
    data = body()
    certificate_number = as_str(
        required(data, "certificate_number"), "certificate_number"
    )
    gl_occurrence_cents = as_int(
        required(data, "gl_occurrence_cents"), "gl_occurrence_cents"
    )
    gl_aggregate_cents = as_int(
        required(data, "gl_aggregate_cents"), "gl_aggregate_cents"
    )
    auto_cents = as_int(required(data, "auto_cents"), "auto_cents")
    umbrella_cents = as_int(required(data, "umbrella_cents"), "umbrella_cents")
    workers_comp = as_enum(
        required(data, "workers_comp"), "workers_comp", WORKERS_COMP_KINDS
    )
    ai_endorsed = as_bool(required(data, "ai_endorsed"), "ai_endorsed")
    wos_endorsed = as_bool(required(data, "wos_endorsed"), "wos_endorsed")
    ptd_endorsed = as_bool(required(data, "ptd_endorsed"), "ptd_endorsed")
    pollution_cents = data.get("pollution_cents", 0)
    if pollution_cents is None:
        pollution_cents = 0
    as_int(pollution_cents, "pollution_cents")
    expires_on = as_str(required(data, "expires_on"), "expires_on")
    try:
        parse_ymd(expires_on)
    except Exception:
        raise ApiError(
            "ERR_VALIDATION", 422, "expires_on must be a YYYY-MM-DD date string"
        )
    evaluation_basis = data.get("evaluation_basis", "FULL_ENDORSEMENTS")
    as_enum(evaluation_basis, "evaluation_basis", EVALUATION_BASES)
    ensure_sub_not_terminal(sub)
    if sub["status"] not in ("AWARDED", "ISSUED", "EXECUTED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            "Subcontract not in AWARDED, ISSUED, or EXECUTED",
        )
    for c in certs_of(sub):
        if c["certificate_number"] == certificate_number:
            raise ApiError(
                "ERR_VALIDATION",
                422,
                "certificate_number must be unique per subcontract",
            )
    rec = {
        "id": new_id(),
        "subcontract_id": sub["id"],
        "certificate_number": certificate_number,
        "gl_occurrence_cents": gl_occurrence_cents,
        "gl_aggregate_cents": gl_aggregate_cents,
        "auto_cents": auto_cents,
        "umbrella_cents": umbrella_cents,
        "workers_comp": workers_comp,
        "ai_endorsed": ai_endorsed,
        "wos_endorsed": wos_endorsed,
        "ptd_endorsed": ptd_endorsed,
        "pollution_cents": pollution_cents,
        "expires_on": expires_on,
        "evaluation_basis": evaluation_basis,
        "compliance_verdict": None,
        "status": "ISSUED",
    }
    stamp(rec)
    pkg = package_of(sub)
    project = get_project(pkg["project_id"])
    evaluate_certificate(rec, sub, pkg, project)
    DB["insurance_certificates"][rec["id"]] = rec
    recompute_insurance_status(sub)
    return ok(ser_cert(rec), status=201)


@bp.get("/subcontracts/<sub_id>/insurance-certificates")
def list_certificates(sub_id):
    auth(STANDARD_READ_ROLES)
    sub = get_subcontract(sub_id)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = sorted_created(certs_of(sub))
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_cert(c) for c in page], total, limit, offset)


@bp.post("/subcontracts/<sub_id>/bond-decision")
def create_bond_decision(sub_id):
    user_id, _ = auth(["OperationsManager"])
    sub = get_subcontract(sub_id)
    data = body()
    trade_history = as_enum(
        required(data, "trade_history"), "trade_history", TRADE_HISTORIES
    )
    decision_rationale = data.get("decision_rationale")
    if decision_rationale is not None:
        as_str(decision_rationale, "decision_rationale")
    ensure_sub_not_terminal(sub)
    if sub["status"] != "AWARDED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in AWARDED"
        )
    if any(b["subcontract_id"] == sub["id"] for b in DB["bond_decisions"].values()):
        raise ApiError(
            "ERR_BOND_DECISION_LOCKED",
            409,
            "An active BondDecision already exists for this subcontract",
        )
    pkg = package_of(sub)
    score = trade_risk_score(sub, pkg, trade_history)
    decision = bond_decision_for(pkg["bonding_policy"], score)
    premium = bond_premium(decision, sub["contract_value_cents"])
    rec = {
        "id": new_id(),
        "subcontract_id": sub["id"],
        "trade_risk_score": score,
        "trade_history": trade_history,
        "decision": decision,
        "premium_cents": premium,
        "decided_by_user_id": user_id,
        "decision_rationale": decision_rationale,
    }
    stamp(rec)
    DB["bond_decisions"][rec["id"]] = rec
    sub["bonding_requirement"] = decision
    touch(sub)
    return ok(ser_bond(rec), status=201)


@bp.get("/subcontracts/<sub_id>/bond-decisions")
def list_bond_decisions(sub_id):
    auth(STANDARD_READ_ROLES)
    sub = get_subcontract(sub_id)
    limit, offset = pagination_args()
    items = sorted_created(
        [b for b in DB["bond_decisions"].values() if b["subcontract_id"] == sub["id"]]
    )
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_bond(b) for b in page], total, limit, offset)
