"""MoveOutRequest routes."""
from flask import Blueprint, request, g

import db
from errors import err
from clock import parse_iso, iso
from middleware import require_auth
from response import success
from services.lookups import get_move_out_request, get_lease, get_deposit_for_lease
from services.validation import (
    require_body, get_body, require_int, require_bool,
)
from services.occ import check_version
from services.rent import void_after
from services.unit_status import update_unit_by_id
from services.audit import record as audit_record
from services.tenant_ledger import recompute_for_tenant


bp = Blueprint("move_out", __name__)


def _check_tenant_ownership_request(req: dict) -> None:
    if g.user_role == "Tenant":
        le = db.leases.get(req["lease_id"])
        if le is None or le.get("tenant_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Tenants can only access their own move-out request")


@bp.get("/move-out-requests/<request_id>")
@require_auth(roles={"PropertyManager", "FinanceOfficer", "Tenant"})
def get_move_out_route(request_id):
    r = get_move_out_request(request_id)
    _check_tenant_ownership_request(r)
    return success(db.public(r))


@bp.post("/move-out-requests/<request_id>/record-inspection")
@require_auth(roles={"PropertyManager"})
def record_inspection(request_id):
    r = get_move_out_request(request_id)
    body = require_body(request)
    check_version(body, r)
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", f"Request must be SUBMITTED (current: {r['status']})")
    findings = body.get("inspection_findings")
    if not isinstance(findings, list):
        raise err("ERR_VALIDATION", "inspection_findings must be a list")
    parsed = []
    for f in findings:
        if not isinstance(f, dict):
            raise err("ERR_VALIDATION", "inspection_findings entries must be objects")
        item = f.get("item")
        sev = f.get("severity")
        est = f.get("estimated_cost_cents")
        if not isinstance(item, str) or not item.strip():
            raise err("ERR_VALIDATION", "inspection_findings[].item must be non-empty string")
        if sev not in {"MINOR", "MAJOR"}:
            raise err("ERR_VALIDATION", "inspection_findings[].severity must be MINOR or MAJOR")
        if isinstance(est, bool) or not isinstance(est, int) or est < 0:
            raise err("ERR_VALIDATION", "inspection_findings[].estimated_cost_cents must be int >= 0")
        parsed.append({"item": item, "severity": sev, "estimated_cost_cents": est})
    r["inspection_findings"] = parsed
    r["status"] = "INSPECTION_DONE"
    db.stamp_update(r)
    return success(db.public(r))


@bp.post("/move-out-requests/<request_id>/confirm-restoration")
@require_auth(roles={"PropertyManager"})
def confirm_restoration(request_id):
    r = get_move_out_request(request_id)
    body = require_body(request)
    check_version(body, r)
    if r["status"] != "INSPECTION_DONE":
        raise err("ERR_INVALID_STATE", f"Request must be INSPECTION_DONE (current: {r['status']})")
    done = require_bool(body, "restoration_done")
    if not done:
        raise err("ERR_RESTORATION_INCOMPLETE", "restoration_done must be true")
    r["restoration_done"] = True
    r["status"] = "RESTORATION_CONFIRMED"
    db.stamp_update(r)
    return success(db.public(r))


@bp.post("/move-out-requests/<request_id>/reject")
@require_auth(roles={"PropertyManager"})
def reject_request(request_id):
    r = get_move_out_request(request_id)
    body = get_body(request)
    check_version(body, r)
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE",
                  f"Only SUBMITTED requests can be rejected (current: {r['status']})")
    r["status"] = "REJECTED"
    db.stamp_update(r)
    # Revert lease to ACTIVE
    le = get_lease(r["lease_id"])
    if le["status"] == "TERMINATING":
        le["status"] = "ACTIVE"
        db.stamp_update(le)
    # Unfreeze deposit
    d = get_deposit_for_lease(r["lease_id"])
    if d is not None:
        d["frozen_status"] = "UNFROZEN"
        db.stamp_update(d)
    return success(db.public(r))


@bp.post("/move-out-requests/<request_id>/finalize")
@require_auth(roles={"FinanceOfficer"})
def finalize_request(request_id):
    r = get_move_out_request(request_id)
    body = get_body(request)
    check_version(body, r)
    if r["status"] != "DEDUCTION_APPROVED":
        raise err("ERR_INVALID_STATE",
                  f"Request must be DEDUCTION_APPROVED (current: {r['status']})")
    le = get_lease(r["lease_id"])
    d = get_deposit_for_lease(le["id"])
    if d is None or d["adjustment_status"] != "SETTLED":
        raise err("ERR_DEPOSIT_NOT_SETTLED",
                  "Deposit must be SETTLED before finalization")
    # All FeeBills for this lease must be PAID or VOIDED
    for b in db.fee_bills.values():
        if b["lease_id"] == le["id"] and b["status"] not in {"PAID", "VOIDED"}:
            raise err("ERR_OUTSTANDING_FEE_BILL",
                      "All fee bills for the lease must be PAID or VOIDED")

    le["status"] = "TERMINATED"
    le["terminated_on"] = r["target_move_out_date"]
    db.stamp_update(le)

    # Void rent schedule items past terminated_on
    void_after(le["id"], parse_iso(le["terminated_on"]))

    # Cascade unit back to VACANT (Deposit settled — by construction)
    update_unit_by_id(le["unit_id"])

    # Cascade move-out to SETTLED
    r["status"] = "SETTLED"
    db.stamp_update(r)

    audit_record(
        subject_kind="LEASE", subject_id=le["id"], action="CONTRACT_TERMINATED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"lease_id": le["id"], "terminated_on": le["terminated_on"]},
    )

    # Recompute tenant ledger (defensive)
    recompute_for_tenant(le["tenant_id"])
    return success(db.public(r))
