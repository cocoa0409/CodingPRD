"""Royalty audit endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response

bp = Blueprint("audits", __name__)

OPEN_AUDIT_STATUSES = ("INITIATED", "FIELDWORK", "FINDINGS_ISSUED")
ADVANCE_PATH = {"INITIATED": "FIELDWORK", "FIELDWORK": "FINDINGS_ISSUED",
                "FINDINGS_ISSUED": "CLOSED"}
FINDING_TERMINAL = ("ACCEPTED", "WAIVED", "RESOLVED")


@bp.post("/licensing/audits")
def create_audit():
    user_id, _ = middleware.require_role("LicensingAnalyst")
    body = common.get_body()
    common.validate_body(body, [
        ("agreement_id", "string", True),
        ("scope_period_start", "datetime", True),
        ("scope_period_end", "datetime", True),
    ])
    # Tier 3: body FK existence
    agr = db.agreements.get(body["agreement_id"])
    if agr is None:
        raise errors.err_agreement_not_found()
    sps = common.parse_dt(body["scope_period_start"])
    spe = common.parse_dt(body["scope_period_end"])
    if spe < sps:
        raise errors.err_validation(
            "scope_period_end must be on or after scope_period_start")
    # Tier 7: agreement must not be DRAFT
    if agr["status"] == "DRAFT":
        raise errors.err_agreement_not_active(
            "Audits may not target a DRAFT agreement")
    # Tier 10: closed-interval overlap with existing open audits
    for a in db.audits.values():
        if a["agreement_id"] == agr["id"] and a["status"] in OPEN_AUDIT_STATUSES:
            aps = common.parse_dt(a["scope_period_start"])
            ape = common.parse_dt(a["scope_period_end"])
            # closed intervals: touching endpoints count as overlap
            if sps <= ape and aps <= spe:
                raise errors.err_audit_scope_overlap()
    # Tier 11: audit window check (inclusive)
    cutoff = common.add_months(common.logical_now(), -agr["audit_window_months"])
    if spe < cutoff:
        raise errors.err_audit_window_expired()

    audit = common.new_resource({
        "agreement_id": body["agreement_id"],
        "scope_period_start": body["scope_period_start"],
        "scope_period_end": body["scope_period_end"],
        "opened_by_user_id": user_id,
        "status": "INITIATED",
    })
    db.audits[audit["id"]] = audit

    # Conditional cascade: FLAGGED reports of this agreement whose half-open
    # period intersects the closed scope become AUDIT_REFERRED.
    for r in db.reports.values():
        if r["agreement_id"] == agr["id"] and r["status"] == "FLAGGED":
            rps = common.parse_dt(r["period_start"])
            rpe = common.parse_dt(r["period_end"])
            # half-open [rps, rpe) vs closed [sps, spe]
            if rps <= spe and sps < rpe:
                r["status"] = "AUDIT_REFERRED"
                common.touch(r)
    return response.success_object(audit, 201)


@bp.get("/licensing/audits")
def list_audits():
    middleware.require_role("LicensingAnalyst", "LegalCounsel")
    args = common.request.args
    agreement_id = args.get("agreement_id")
    status = args.get("status")
    items = list(db.audits.values())
    if agreement_id is not None:
        items = [a for a in items if a["agreement_id"] == agreement_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/audits/<aid>")
def get_audit(aid):
    middleware.require_role("LicensingAnalyst", "LegalCounsel")
    audit = db.audits.get(aid)
    if audit is None:
        raise errors.err_audit_not_found()
    return response.success_object(audit)


@bp.post("/licensing/audits/<aid>/advance")
def advance_audit(aid):
    middleware.require_role("LicensingAnalyst")
    audit = db.audits.get(aid)
    if audit is None:
        raise errors.err_audit_not_found()
    body = common.get_body()
    common.validate_body(body, [
        ("to_state", "enum:INITIATED,FIELDWORK,FINDINGS_ISSUED,CLOSED", True),
    ])
    to_state = body["to_state"]
    expected = ADVANCE_PATH.get(audit["status"])
    if expected is None or to_state != expected:
        raise errors.err_audit_invalid_state(
            f"Cannot advance from {audit['status']} to {to_state}")
    if to_state == "CLOSED":
        for f in db.findings.values():
            if f["audit_id"] == audit["id"] and f["status"] not in FINDING_TERMINAL:
                raise errors.err_audit_invalid_state(
                    "Audit cannot close while findings are non-terminal")
    audit["status"] = to_state
    common.touch(audit)
    return response.success_object(audit)
