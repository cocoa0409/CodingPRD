"""Transcript audit cases and reversing entries; transcript entry reads."""
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE, \
    ERR_AUDIT_ENTRY_MISMATCH, ERR_ENTRY_ALREADY_REVERSED
from serializers import ser_case, ser_entry
from services import mint_transcript_entry, recompute_plan
from validate import req_str, req_int

bp = Blueprint("audit", __name__)


def get_case_or_404(cid):
    c = store.audit_cases.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "audit case not found")
    return c


@bp.post("/pd/audit-cases")
def create_case():
    ctx = require_role("Auditor")
    body = get_body()
    employee_id = req_str(body, "employee_id")
    fy = req_int(body, "fiscal_year")
    if employee_id not in store.employees:
        raise err(ERR_NOT_FOUND, "employee_id not found")
    c = new_resource()
    c.update({
        "employee_id": employee_id,
        "fiscal_year": fy,
        "status": "OPEN",
        "findings_count": 0,
        "opened_by_user_id": ctx.user_id,
    })
    store.audit_cases[c["id"]] = c
    return ok(ser_case(c), 201)


@bp.get("/pd/audit-cases/<cid>")
def get_case(cid):
    require_any_role()
    return ok(ser_case(get_case_or_404(cid)), 200)


@bp.get("/pd/audit-cases")
def list_cases():
    require_any_role()
    items = store.audit_cases.values()
    emp = request.args.get("employee_id")
    if emp is not None:
        items = [c for c in items if c["employee_id"] == emp]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_case(c) for c in sort_by_created(items)])


@bp.post("/pd/audit-cases/<cid>/raise-finding")
def raise_finding(cid):
    require_role("Auditor")
    c = get_case_or_404(cid)
    body = get_body()
    req_str(body, "note")
    if c["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "findings are raised from OPEN")
    c["status"] = "FINDINGS_RAISED"
    c["findings_count"] += 1
    touch(c)
    return ok(ser_case(c), 200)


@bp.post("/pd/audit-cases/<cid>/reverse-entry")
def reverse_entry(cid):
    require_role("Auditor")
    c = get_case_or_404(cid)
    body = get_body()
    entry_id = req_str(body, "transcript_entry_id")
    req_str(body, "reason")
    entry = store.transcript_entries.get(entry_id)
    if entry is None:
        raise err(ERR_NOT_FOUND, "transcript_entry_id not found")
    # state (6): case posture, then the entry's own reversal state
    if c["status"] not in ("OPEN", "FINDINGS_RAISED"):
        raise err(ERR_INVALID_STATE, "case is not open for reversals")
    if entry["status"] != "AWARDED":
        raise err(ERR_ENTRY_ALREADY_REVERSED, "entry is already REVERSED")
    # alignment (8)
    if (entry["employee_id"] != c["employee_id"]
            or entry["fiscal_year"] != c["fiscal_year"]):
        raise err(ERR_AUDIT_ENTRY_MISMATCH,
                  "entry does not match the case's employee + fiscal year")
    reversal = mint_transcript_entry(
        employee_id=entry["employee_id"],
        source_type="AUDIT_REVERSAL",
        source_id=entry["id"],
        growth_plan_id=entry["growth_plan_id"],
        clock_hours=-entry["clock_hours"],
        counts_toward_lane=entry["counts_toward_lane"],
    )
    # minted values derive from positive-hours conversion; force exact
    # negation of the original entry's stored values instead.
    reversal["clock_hours"] = -entry["clock_hours"]
    reversal["district_credit"] = -entry["district_credit"]
    reversal["state_ceu"] = -entry["state_ceu"]
    entry["status"] = "REVERSED"
    entry["reversed_by_entry_id"] = reversal["id"]
    touch(entry)
    # lane_credit_balance recomputes on read; lane itself is not rolled back
    if entry["growth_plan_id"]:
        plan = store.growth_plans.get(entry["growth_plan_id"])
        if plan is not None:
            recompute_plan(plan)
    c["findings_count"] += 1
    if c["status"] == "OPEN":
        c["status"] = "FINDINGS_RAISED"
    touch(c)
    return ok(ser_entry(reversal), 200)


@bp.post("/pd/audit-cases/<cid>/resolve")
def resolve_case(cid):
    require_role("Auditor")
    get_body()
    c = get_case_or_404(cid)
    if c["status"] != "FINDINGS_RAISED" or c["findings_count"] < 1:
        raise err(ERR_INVALID_STATE, "resolution requires raised findings")
    c["status"] = "RESOLVED"
    touch(c)
    return ok(ser_case(c), 200)


@bp.post("/pd/audit-cases/<cid>/close-clean")
def close_clean(cid):
    require_role("Auditor")
    get_body()
    c = get_case_or_404(cid)
    if c["status"] != "OPEN" or c["findings_count"] != 0:
        raise err(ERR_INVALID_STATE,
                  "only an OPEN case with no findings closes clean")
    c["status"] = "CLOSED_CLEAN"
    touch(c)
    return ok(ser_case(c), 200)


@bp.get("/pd/transcript-entries/<eid>")
def get_entry(eid):
    require_any_role()
    e = store.transcript_entries.get(eid)
    if e is None:
        raise err(ERR_NOT_FOUND, "transcript entry not found")
    return ok(ser_entry(e), 200)
