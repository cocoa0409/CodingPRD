"""RepairEstimate routes (PRD §3.4)."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate)
from response import success, list_success
from services import calc
from services.lookups import submitted_estimate

bp = Blueprint("repair_estimates", __name__)

READ_ROLES = {"ClaimsSupervisor", "ClaimsAdjuster", "TotalLossAdjuster"}


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise err("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    cleaned = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise err("ERR_INVALID_REQUEST", "each line must be an object")
        labor = ln.get("labor_cents")
        parts = ln.get("parts_cents")
        if not isinstance(labor, int) or isinstance(labor, bool):
            raise err("ERR_INVALID_REQUEST", "labor_cents must be an integer")
        if not isinstance(parts, int) or isinstance(parts, bool):
            raise err("ERR_INVALID_REQUEST", "parts_cents must be an integer")
        description = ln.get("description")
        if description is not None and not isinstance(description, str):
            raise err("ERR_INVALID_REQUEST", "description must be a string")
        cleaned.append({
            "description": description,
            "labor_cents": labor,
            "parts_cents": parts,
        })
    return cleaned


@bp.route("/repair-estimates", methods=["POST"])
def create_repair_estimate():
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster"})
    body = get_json_body()
    require_fields(body, ["claim_id", "lines"])
    claim = require_resource(db.claims, body["claim_id"], "claim")
    lines = _validate_lines(body["lines"])

    rec = {
        "claim_id": claim["id"],
        "authored_by_adjuster_id": principal.user_id,
        "lines": lines,
        "repair_total_cents": calc.repair_total(lines),
        "status": "DRAFT",
    }
    db.insert(db.repair_estimates, rec)
    return success(S.repair_estimate(rec), status=201)


@bp.route("/repair-estimates/<eid>", methods=["GET"])
def get_repair_estimate(eid):
    principal = authenticate()
    authorize(principal, READ_ROLES)
    rec = require_resource(db.repair_estimates, eid, "repair estimate")
    return success(S.repair_estimate(rec), status=200)


@bp.route("/repair-estimates", methods=["GET"])
def list_repair_estimates():
    principal = authenticate()
    authorize(principal, READ_ROLES)
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    authored_by = request.args.get("authored_by_adjuster_id")
    status = request.args.get("status")
    rows = list(db.repair_estimates.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if authored_by is not None:
        rows = [r for r in rows if r["authored_by_adjuster_id"] == authored_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([S.repair_estimate(r) for r in page], limit, offset, total)


@bp.route("/repair-estimates/<eid>/submit", methods=["POST"])
def submit_repair_estimate(eid):
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster"})
    estimate = require_resource(db.repair_estimates, eid, "repair estimate")
    claim = db.claims.get(estimate["claim_id"])

    if estimate["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "estimate is not DRAFT")
    if claim is None or claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "parent claim is not UNDER_REVIEW")
    # Only the assigned adjuster may submit.
    if estimate["authored_by_adjuster_id"] != claim["assigned_adjuster_id"]:
        raise err("ERR_INVALID_STATE",
                  "only the assigned adjuster may submit this estimate")

    # Supersede any prior SUBMITTED estimate on the same claim (cross-entity).
    prior = submitted_estimate(claim["id"])
    if prior is not None and prior["id"] != estimate["id"]:
        prior["status"] = "SUPERSEDED"
        db.touch(prior)

    estimate["repair_total_cents"] = calc.repair_total(estimate["lines"])
    estimate["status"] = "SUBMITTED"
    db.touch(estimate)
    return success(S.repair_estimate(estimate), status=200)
