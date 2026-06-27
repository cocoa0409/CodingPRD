"""WarrantyClaim routes: file (OCC), review loop, adjudicate, withdraw."""
from flask import Blueprint, request

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import get_now
from errors import err
from response import success
from serialize import out
from timeutil import parse, whole_months_between
from validate import get_body, opt_enum, require_enum, require_int, require_str
from routes.common import customer_owns, find_or_404, render_list

bp = Blueprint("warranty", __name__)


@bp.route("/units/<unit_id>/warranty-claims", methods=["POST"])
def file_claim(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    unit = find_or_404(db.units, unit_id)
    body = get_body()
    description = require_str(body, "description")
    expected_unit_version = require_int(body, "expected_unit_version")

    # Ownership (priority 6) before OCC (priority 7), both after body parse.
    customer_owns(principal, unit["customer_id"])

    # OCC (priority 7) — after ownership, before state
    if expected_unit_version != unit["version"]:
        raise err("ERR_STALE_VERSION", "Unit version is stale")

    rec = db.base_record(full_common=True)
    rec.update({
        "unit_id": unit_id,
        "description": description,
        "status": "OPEN",
        "resolution": None,
        "refund_cents": 0,
        "refund_basis": "CALENDAR",
        "dispatch_id": None,
    })
    db.warranty_claims[rec["id"]] = rec
    # Filing bumps the unit's version.
    db.touch(unit)
    return success(out(rec), status=201)


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    records = list(db.warranty_claims.values())
    for f in ("unit_id", "dispatch_id"):
        if f in request.args:
            val = request.args.get(f)
            records = [r for r in records if r.get(f) == val]
    return render_list(records)


@bp.route("/warranty-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.warranty_claims, claim_id)
    return success(out(rec), status=200)


@bp.route("/warranty-claims/<claim_id>/review", methods=["POST"])
def review_claim(claim_id):
    principal = get_principal()
    require_roles(principal, {"ComplianceOfficer"})
    claim = find_or_404(db.warranty_claims, claim_id)
    if claim["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Claim must be OPEN to review")
    unit = db.units.get(claim["unit_id"])
    if unit["warranty_status"] != "ACTIVE":
        raise err("ERR_WARRANTY_LAPSED", "Warranty is not ACTIVE")
    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)
    return success(out(claim), status=200)


@bp.route("/warranty-claims/<claim_id>/return-for-info", methods=["POST"])
def return_claim(claim_id):
    principal = get_principal()
    require_roles(principal, {"ComplianceOfficer"})
    claim = find_or_404(db.warranty_claims, claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim must be UNDER_REVIEW to return")
    claim["status"] = "OPEN"
    db.touch(claim)
    return success(out(claim), status=200)


@bp.route("/warranty-claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate_claim(claim_id):
    principal = get_principal()
    require_roles(principal, {"ComplianceOfficer"})
    claim = find_or_404(db.warranty_claims, claim_id)
    body = get_body()
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})

    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim must be UNDER_REVIEW to adjudicate")

    unit = db.units.get(claim["unit_id"])

    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["resolution"] = "NO_FAULT_FOUND"
        db.touch(claim)
        return success(out(claim), status=200)

    # APPROVE
    if unit["warranty_status"] != "ACTIVE":
        raise err("ERR_WARRANTY_LAPSED", "Warranty is not ACTIVE")
    resolution = require_enum(body, "resolution", {"REPAIR_COVERED", "PRORATED_REFUND"})
    refund_basis = opt_enum(body, "refund_basis", {"CALENDAR", "USAGE"}, default="CALENDAR")

    claim["resolution"] = resolution
    claim["refund_basis"] = refund_basis

    if resolution == "PRORATED_REFUND":
        ws = parse(unit["warranty_start"])
        calendar_elapsed = whole_months_between(ws, get_now()) if ws else 0
        claim["refund_cents"] = calc.run_warranty_refund(
            unit["warranty_total_months"], calendar_elapsed,
            unit["runtime_hours"], refund_basis,
        )
    elif resolution == "REPAIR_COVERED":
        dispatch = db.base_record(full_common=True)
        dispatch.update({
            "unit_id": unit["id"],
            "origin": "WARRANTY",
            "warranty_claim_id": claim["id"],
            "assigned_tech_id": None,
            "status": "REQUESTED",
            "labor_cents": 0,
            "parts_cents": 0,
            "billable": False,
            "invoice_total_cents": 0,
            "resolved_by_tech_id": None,
            "runtime_added_hours": 0,
        })
        db.repair_dispatches[dispatch["id"]] = dispatch
        claim["dispatch_id"] = dispatch["id"]

    claim["status"] = "APPROVED"
    db.touch(claim)
    return success(out(claim), status=200)


@bp.route("/warranty-claims/<claim_id>/withdraw", methods=["POST"])
def withdraw_claim(claim_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    claim = find_or_404(db.warranty_claims, claim_id)
    unit = db.units.get(claim["unit_id"])
    customer_owns(principal, unit["customer_id"])
    if claim["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "Claim must be OPEN or UNDER_REVIEW to withdraw")
    claim["status"] = "WITHDRAWN"
    db.touch(claim)
    return success(out(claim), status=200)
