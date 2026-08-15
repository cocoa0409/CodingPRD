"""Audit case endpoints (PRD 3.8)."""

from datetime import date

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_audit_or_404, find_applicable_rule,
    missed_due_date_no_rolldorward, round_half_up_cents, floor_pct,
    property_has_line_in_submitted_or_accepted, BP_DENOMINATOR,
)

bp = Blueprint("audits", __name__)

AUDIT_SEQUENCE = ["OPENED", "FIELDWORK", "FINDINGS_ISSUED", "CLOSED"]


def audit_view(a):
    return {
        "id": a["id"],
        "state_code": a["state_code"],
        "lookback_start_year": a["lookback_start_year"],
        "lookback_end_year": a["lookback_end_year"],
        "status": a["status"],
        "estimated_exposure_cents": a["estimated_exposure_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/escheatment/audit-cases")
def create_audit():
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    data = mw.body_json()
    state_code = mw.req_string(data, "state_code")
    start_year = mw.req_int(data, "lookback_start_year", min_value=1)
    end_year = mw.req_int(data, "lookback_end_year", min_value=1)
    if end_year < start_year:
        raise_error(
            errors.ERR_INVALID_REQUEST,
            "lookback_end_year must be >= lookback_start_year",
        )
    for existing in db.audit_cases.values():
        if existing["state_code"] != state_code or existing["status"] == "CLOSED":
            continue
        # Closed-interval overlap: touching boundary years count as overlap.
        if not (end_year < existing["lookback_start_year"] or start_year > existing["lookback_end_year"]):
            raise_error(
                errors.ERR_AUDIT_LOOKBACK_OVERLAP,
                "Lookback window overlaps another non-CLOSED audit for this state",
            )
    audit = new_entity({
        "state_code": state_code,
        "lookback_start_year": start_year,
        "lookback_end_year": end_year,
        "status": "OPENED",
        "estimated_exposure_cents": None,
    })
    db.audit_cases[audit["id"]] = audit
    return resp.success(audit_view(audit), "object", 201)


@bp.get("/escheatment/audit-cases")
def list_audits():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    limit, offset = mw.pagination_params()
    items = list(db.audit_cases.values())
    state_code = mw.request.args.get("state_code")
    if state_code is not None:
        items = [a for a in items if a["state_code"] == state_code]
    status = mw.request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([audit_view(a) for a in page], "array", 200, pagination=meta)


@bp.get("/escheatment/audit-cases/<auditId>")
def get_audit(auditId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    audit = get_audit_or_404(auditId)
    return resp.success(audit_view(audit), "object", 200)


def _compute_exposure(audit):
    """audit_exposure_estimate: candidate filter + per-candidate penalty and
    interest, summed. Returns (estimated_exposure_cents, candidate_ids)."""
    window_start = date(audit["lookback_start_year"], 1, 1)
    window_end = date(audit["lookback_end_year"], 12, 31)
    current = clock.today()
    candidates = []
    for prop in db.properties.values():
        if prop["state_code"] != audit["state_code"]:
            continue
        if prop["status"] not in ("DORMANT", "DUE_DILIGENCE", "REPORTABLE"):
            continue
        if prop["dormancy_date"] is None:
            continue
        if not (window_start <= prop["dormancy_date"] <= window_end):
            continue
        if property_has_line_in_submitted_or_accepted(prop["id"]):
            continue
        candidates.append(prop)
    # Processing order: earliest dormancy_date first, ties by created_at ASC.
    candidates.sort(key=lambda p: (p["dormancy_date"], p["created_at"], p["id"]))

    total = 0
    for prop in candidates:
        rule = find_applicable_rule(
            prop["state_code"], prop["property_type"], prop["last_contact_date"]
        )
        if rule is None:
            continue
        missed_due = missed_due_date_no_rolldorward(rule, prop["dormancy_date"])
        days_past_due = max(0, (current - missed_due).days)
        if days_past_due <= rule["gross_negligence_day_threshold"]:
            rate = rule["daily_penalty_cents"]
        else:
            rate = rule["gross_daily_penalty_cents"]
        cap = floor_pct(rule["penalty_cap_pct"], prop["original_value_cents"])
        penalty_i = min(rate * days_past_due, cap)
        interest_i = round_half_up_cents(
            prop["original_value_cents"] * rule["annual_interest_rate_bp"] * days_past_due,
            BP_DENOMINATOR,
        )
        total += prop["original_value_cents"] + penalty_i + interest_i
    return total, [p["id"] for p in candidates]


@bp.post("/escheatment/audit-cases/<auditId>/advance")
def advance_audit(auditId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    mw.body_json(required=False)
    audit = get_audit_or_404(auditId)
    if audit["status"] == "CLOSED":
        raise_error(
            errors.ERR_AUDIT_CASE_NOT_ADVANCEABLE,
            "Advance from CLOSED is not possible",
        )
    next_status = AUDIT_SEQUENCE[AUDIT_SEQUENCE.index(audit["status"]) + 1]
    audit["status"] = next_status
    if next_status == "FINDINGS_ISSUED":
        exposure, candidate_ids = _compute_exposure(audit)
        audit["estimated_exposure_cents"] = exposure
        audit["_candidate_property_ids"] = candidate_ids
    touch(audit)
    return resp.success(audit_view(audit), "object", 200)


@bp.get("/escheatment/audit-cases/<auditId>/exposure")
def get_exposure(auditId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    audit = get_audit_or_404(auditId)
    if "estimated_exposure_cents" in audit and audit["estimated_exposure_cents"] is not None:
        exposure = audit["estimated_exposure_cents"]
        candidate_ids = audit.get("_candidate_property_ids", [])
    else:
        exposure, candidate_ids = _compute_exposure(audit)
    return resp.success(
        {
            "estimated_exposure_cents": exposure,
            "candidate_property_ids": candidate_ids,
        },
        "object",
        200,
    )
