"""SubrogationCase routes (PRD §3.10)."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     require_int, optional_int, parse_pagination, paginate)
from response import success, list_success
from services import calc

bp = Blueprint("subrogation_cases", __name__)

READ_ROLES = {"ClaimsSupervisor", "SubrogationSpecialist"}


def _recompute_recoverable(case, claim):
    policy = db.policies.get(claim["policy_id"])
    rule = policy["comparative_fault_rule"] if policy else "MODIFIED_50"
    case["recoverable_cents"] = calc.subrogation_recovery(
        case["demand_cents"], claim["insured_fault_pct"], rule)


@bp.route("/subrogation-cases", methods=["POST"])
def create_subrogation_case():
    principal = authenticate()
    authorize(principal, {"SubrogationSpecialist"})
    body = get_json_body()
    require_fields(body, ["claim_id", "target_party_id", "demand_cents"])
    claim = require_resource(db.claims, body["claim_id"], "claim")
    target = require_resource(db.claim_parties, body["target_party_id"], "claim party")
    demand_cents = require_int(body, "demand_cents")

    rec = {
        "claim_id": claim["id"],
        "target_party_id": target["id"],
        "demand_cents": demand_cents,
        "recoverable_cents": 0,
        "recovered_cents": 0,
        "status": "OPEN",
    }
    _recompute_recoverable(rec, claim)
    db.insert(db.subrogation_cases, rec)
    return success(S.subrogation_case(rec), status=201)


@bp.route("/subrogation-cases/<sid>", methods=["GET"])
def get_subrogation_case(sid):
    principal = authenticate()
    authorize(principal, READ_ROLES)
    rec = require_resource(db.subrogation_cases, sid, "subrogation case")
    return success(S.subrogation_case(rec), status=200)


@bp.route("/subrogation-cases", methods=["GET"])
def list_subrogation_cases():
    principal = authenticate()
    authorize(principal, READ_ROLES)
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    target_party_id = request.args.get("target_party_id")
    status = request.args.get("status")
    rows = list(db.subrogation_cases.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if target_party_id is not None:
        rows = [r for r in rows if r["target_party_id"] == target_party_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([S.subrogation_case(r) for r in page], limit, offset, total)


@bp.route("/subrogation-cases/<sid>/send-demand", methods=["POST"])
def send_demand(sid):
    principal = authenticate()
    authorize(principal, {"SubrogationSpecialist"})
    case = require_resource(db.subrogation_cases, sid, "subrogation case")
    body = get_json_body()
    claim = db.claims.get(case["claim_id"])

    if case["status"] not in ("OPEN", "NEGOTIATING"):
        raise err("ERR_INVALID_STATE", "send-demand not allowed from %s" % case["status"])

    # Optional revised demand (mandatory in spirit for the NEGOTIATING revision).
    if "demand_cents" in body and body["demand_cents"] is not None:
        revised = body["demand_cents"]
        if not isinstance(revised, int) or isinstance(revised, bool):
            raise err("ERR_INVALID_REQUEST", "demand_cents must be an integer")
        case["demand_cents"] = revised

    # Parent claim must be SETTLED.
    if claim is None or claim["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "parent claim is not SETTLED")

    _recompute_recoverable(case, claim)
    if case["recoverable_cents"] <= 0:
        raise err("ERR_NO_RECOVERABLE_AMOUNT", "recoverable_cents is not positive")

    case["status"] = "DEMAND_SENT"
    db.touch(case)
    return success(S.subrogation_case(case), status=200)


@bp.route("/subrogation-cases/<sid>/begin-negotiation", methods=["POST"])
def begin_negotiation(sid):
    principal = authenticate()
    authorize(principal, {"SubrogationSpecialist"})
    case = require_resource(db.subrogation_cases, sid, "subrogation case")
    if case["status"] != "DEMAND_SENT":
        raise err("ERR_INVALID_STATE",
                  "begin-negotiation not allowed from %s" % case["status"])
    case["status"] = "NEGOTIATING"
    db.touch(case)
    return success(S.subrogation_case(case), status=200)


@bp.route("/subrogation-cases/<sid>/resolve", methods=["POST"])
def resolve_subrogation_case(sid):
    principal = authenticate()
    authorize(principal, {"SubrogationSpecialist"})
    case = require_resource(db.subrogation_cases, sid, "subrogation case")
    body = get_json_body()
    require_fields(body, ["recovered_cents"])
    recovered = require_int(body, "recovered_cents")
    claim = db.claims.get(case["claim_id"])

    # State guard: RESOLVED reachable from NEGOTIATING; CLOSED_NO_RECOVERY from
    # DEMAND_SENT or NEGOTIATING.
    if recovered > 0:
        if case["status"] != "NEGOTIATING":
            raise err("ERR_INVALID_STATE",
                      "resolve (recovered>0) not allowed from %s" % case["status"])
    else:
        if case["status"] not in ("DEMAND_SENT", "NEGOTIATING"):
            raise err("ERR_INVALID_STATE",
                      "resolve (recovered==0) not allowed from %s" % case["status"])

    # 0 <= recovered <= recoverable.
    if recovered < 0 or recovered > case["recoverable_cents"]:
        raise err("ERR_RECOVERY_EXCEEDS_DEMAND",
                  "recovered_cents must be within 0..recoverable_cents")

    if recovered == 0:
        case["status"] = "CLOSED_NO_RECOVERY"
        case["recovered_cents"] = 0
        db.touch(case)
        return success(S.subrogation_case(case), status=200)

    # Hop 1: RESOLVED + recovered stored.
    case["status"] = "RESOLVED"
    case["recovered_cents"] = recovered
    db.touch(case)

    # Hop 2: SUBROGATION_RECOVERY disbursement for -recovered (inbound credit).
    disb = {
        "claim_id": claim["id"],
        "disbursement_type": "SUBROGATION_RECOVERY",
        "amount_cents": -recovered,
        "source_entity_id": claim["id"],
        "status": "APPROVED",
    }
    db.insert(db.disbursements, disb)
    # Hop 3: recompute parent Claim.total_disbursed_cents.
    calc.refresh_claim_ledger(claim)
    return success(S.subrogation_case(case), status=200)
