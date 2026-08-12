"""Finance routes: chargeback batches, compliance audits, consumption report,
and the test-driving logical clock."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from auth import require_roles
from envelope import ok, ok_list
from errors import err
from helpers import (ADMIN_FEE_BPS, body, get_or_404, paged, pagination_params,
                     qparam, req_date, req_datetime, req_enum, req_str,
                     resolve_price, run_sweeps)
from util import new_record, parse_date, parse_datetime, render_clock, touch

bp = Blueprint("finance", __name__)

AUDIT_SCOPES = {"OVERRIDE_USAGE", "INSPECTION_COMPLIANCE"}


# --- ChargebackBatch -------------------------------------------------------

@bp.post("/chargeback-batches")
def create_batch():
    require_roles("FinanceAnalyst")
    b = body()
    cc_id = req_str(b, "cost_center_id")
    ps = req_date(b, "period_start")
    pe = req_date(b, "period_end")
    if parse_date(pe) <= parse_date(ps):
        err("ERR_VALIDATION_FAILED", "period_end must be > period_start")
    get_or_404(db.cost_centers, cc_id, "ERR_COST_CENTER_NOT_FOUND")
    nps, npe = parse_date(ps), parse_date(pe)
    for bt in db.batches.values():
        if bt["cost_center_id"] != cc_id:
            continue
        ops, ope = parse_date(bt["period_start"]), parse_date(bt["period_end"])
        # half-open intersection; adjacency (end == start) allowed
        if nps < ope and npe > ops:
            err("ERR_BATCH_PERIOD_OVERLAP",
                "batch period overlaps an existing batch for this cost center")
    rec = new_record({
        "cost_center_id": cc_id,
        "period_start": ps,
        "period_end": pe,
        "line_count": 0,
        "snapshot_total_cents": 0,
        "rerated_total_cents": 0,
        "adjustment_cents": 0,
        "admin_fee_cents": 0,
        "total_cents": 0,
        "status": "OPEN",
    })
    db.batches[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/chargeback-batches")
def list_batches():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.batches.values())
    for param in ("cost_center_id", "status"):
        v = qparam(param)
        if v is not None:
            rows = [bt for bt in rows if bt.get(param) == v]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/chargeback-batches/<batchId>")
def get_batch(batchId):
    require_roles("Any")
    return ok(get_or_404(db.batches, batchId, "ERR_CHARGEBACK_BATCH_NOT_FOUND"))


@bp.post("/chargeback-batches/<batchId>/close")
def close_batch(batchId):
    require_roles("FinanceAnalyst")
    body()
    batch = get_or_404(db.batches, batchId, "ERR_CHARGEBACK_BATCH_NOT_FOUND")
    if batch["status"] != "OPEN":
        err("ERR_BATCH_INVALID_STATE", "close requires OPEN")
    ps, pe = parse_date(batch["period_start"]), parse_date(batch["period_end"])
    swept = [t for t in db.issuances.values()
             if t["cost_center_id"] == batch["cost_center_id"]
             and t["status"] == "POSTED"
             and t["chargeback_batch_id"] is None
             and ps <= t["vended_at"].date() < pe]
    if not swept and batch["adjustment_cents"] == 0:
        err("ERR_EMPTY_CHARGEBACK_BATCH",
            "close requires a non-empty sweep set or non-zero adjustment_cents")
    for t in swept:
        t["chargeback_batch_id"] = batch["id"]
        touch(t)
    batch["line_count"] = len(swept)
    batch["snapshot_total_cents"] = sum(t["line_total_cents"] for t in swept)
    # rerate: chronological replay with a running cumulative per item
    order = sorted(swept, key=lambda t: (t["vended_at"], t["_seq"]))
    running = defaultdict(int)
    rerated = 0
    fee = 0
    for t in order:
        item = db.items.get(t["item_id"])
        price = resolve_price(item, t["vended_at"].date(), running[t["item_id"]])
        line = price * t["qty"]
        running[t["item_id"]] += t["qty"]
        rerated += line
        fee += int((Decimal(line) * ADMIN_FEE_BPS / Decimal(10000))
                   .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    batch["rerated_total_cents"] = rerated
    batch["admin_fee_cents"] = fee
    batch["total_cents"] = rerated + batch["adjustment_cents"] + fee
    batch["status"] = "CLOSED"
    touch(batch)
    cc = db.cost_centers.get(batch["cost_center_id"])
    if cc is not None:
        cc["ytd_charged_cents"] += batch["total_cents"]
        touch(cc)
    return ok(batch)


@bp.post("/chargeback-batches/<batchId>/dispute")
def dispute_batch(batchId):
    require_roles("Manager")
    body()
    batch = get_or_404(db.batches, batchId, "ERR_CHARGEBACK_BATCH_NOT_FOUND")
    if batch["status"] != "CLOSED":
        err("ERR_BATCH_INVALID_STATE", "dispute requires CLOSED")
    batch["status"] = "DISPUTED"
    touch(batch)
    return ok(batch)


@bp.post("/chargeback-batches/<batchId>/settle")
def settle_batch(batchId):
    require_roles("FinanceAnalyst")
    body()
    batch = get_or_404(db.batches, batchId, "ERR_CHARGEBACK_BATCH_NOT_FOUND")
    if batch["status"] not in ("CLOSED", "DISPUTED"):
        err("ERR_BATCH_INVALID_STATE", "settle requires CLOSED or DISPUTED")
    batch["status"] = "SETTLED"
    touch(batch)
    return ok(batch)


# --- ComplianceAudit -------------------------------------------------------

@bp.post("/compliance-audits")
def create_audit():
    require_roles("ComplianceAuditor")
    b = body()
    scope = req_enum(b, "scope", AUDIT_SCOPES)
    ps = req_date(b, "period_start")
    pe = req_date(b, "period_end")
    if parse_date(pe) < parse_date(ps):
        err("ERR_VALIDATION_FAILED", "period_end must be >= period_start")
    rec = new_record({
        "scope": scope,
        "period_start": ps,
        "period_end": pe,
        "exceptions_count": 0,
        "findings_detail": [],
        "status": "DRAFT",
    })
    db.audits[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/compliance-audits/<auditId>")
def get_audit(auditId):
    require_roles("Any")
    return ok(get_or_404(db.audits, auditId, "ERR_COMPLIANCE_AUDIT_NOT_FOUND"))


@bp.post("/compliance-audits/<auditId>/begin-fieldwork")
def begin_fieldwork(auditId):
    require_roles("ComplianceAuditor")
    body()
    audit = get_or_404(db.audits, auditId, "ERR_COMPLIANCE_AUDIT_NOT_FOUND")
    if audit["status"] != "DRAFT":
        err("ERR_AUDIT_INVALID_STATE", "begin-fieldwork requires DRAFT")
    aps, ape = parse_date(audit["period_start"]), parse_date(audit["period_end"])
    for bt in db.batches.values():
        if bt["status"] != "OPEN":
            continue
        # closed-interval overlap on both sides
        if (parse_date(bt["period_start"]) <= ape
                and parse_date(bt["period_end"]) >= aps):
            err("ERR_OPEN_BATCHES_EXIST",
                "an overlapping OPEN chargeback batch exists")
    audit["status"] = "FIELDWORK"
    touch(audit)
    return ok(audit)


@bp.post("/compliance-audits/<auditId>/file-findings")
def file_findings(auditId):
    require_roles("ComplianceAuditor")
    body()
    audit = get_or_404(db.audits, auditId, "ERR_COMPLIANCE_AUDIT_NOT_FOUND")
    if audit["status"] != "FIELDWORK":
        err("ERR_AUDIT_INVALID_STATE", "file-findings requires FIELDWORK")
    aps, ape = parse_date(audit["period_start"]), parse_date(audit["period_end"])
    findings = []
    if audit["scope"] == "OVERRIDE_USAGE":
        for o in sorted(db.overrides.values(), key=lambda x: x["_seq"]):
            # closed-interval intersection with the audit period
            if not (parse_date(o["valid_from"]) <= ape
                    and parse_date(o["valid_until"]) >= aps):
                continue
            drawn = sum(t["override_drawn_qty"] for t in db.issuances.values()
                        if t.get("manager_override_id") == o["id"]
                        and t["status"] == "POSTED")
            if o["consumed_qty"] != drawn:
                findings.append({
                    "finding_type": "OVERRIDE_CONSUMPTION_MISMATCH",
                    "entity_id": o["id"],
                    "detail": "consumed_qty %d != POSTED override_drawn_qty sum %d"
                              % (o["consumed_qty"], drawn),
                })
    else:  # INSPECTION_COMPLIANCE
        for u in sorted(db.units.values(), key=lambda x: x["_seq"]):
            if u["status"] in ("INSPECTION_DUE", "QUARANTINED"):
                findings.append({
                    "finding_type": "UNIT_INSPECTION_LAPSED",
                    "entity_id": u["id"],
                    "detail": "unit %s in status %s" % (u["serial_number"], u["status"]),
                })
    audit["findings_detail"] = findings
    audit["exceptions_count"] = len(findings)
    audit["status"] = "FINDINGS_FILED"
    touch(audit)
    return ok(audit)


@bp.post("/compliance-audits/<auditId>/close")
def close_audit(auditId):
    require_roles("ComplianceAuditor")
    body()
    audit = get_or_404(db.audits, auditId, "ERR_COMPLIANCE_AUDIT_NOT_FOUND")
    if audit["status"] != "FINDINGS_FILED":
        err("ERR_AUDIT_INVALID_STATE", "close requires FINDINGS_FILED")
    audit["status"] = "CLOSED"
    touch(audit)
    return ok(audit)


# --- Reports ---------------------------------------------------------------

@bp.get("/reports/consumption")
def consumption_report():
    require_roles("Any")
    cc_id = request.args.get("cost_center_id")
    ps = request.args.get("period_start")
    pe = request.args.get("period_end")
    if not cc_id or not ps or not pe:
        err("ERR_VALIDATION_FAILED",
            "cost_center_id, period_start and period_end are required")
    try:
        psd, ped = parse_date(ps), parse_date(pe)
    except Exception:
        err("ERR_VALIDATION_FAILED", "period bounds must be ISO dates")
    if ped <= psd:
        err("ERR_VALIDATION_FAILED", "period_end must be > period_start")
    get_or_404(db.cost_centers, cc_id, "ERR_COST_CENTER_NOT_FOUND")
    lines = [t for t in db.issuances.values()
             if t["cost_center_id"] == cc_id and t["status"] == "POSTED"
             and psd <= t["vended_at"].date() < ped]
    return ok({
        "cost_center_id": cc_id,
        "period_start": ps,
        "period_end": pe,
        "line_count": len(lines),
        "total_qty": sum(t["qty"] for t in lines),
        "total_amount_cents": sum(t["line_total_cents"] for t in lines),
    })


# --- Logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("EHSAdministrator")
    b = body()
    raw = req_datetime(b, "to_iso8601")
    db.clock = parse_datetime(raw)
    run_sweeps()
    return ok({"current_utc": render_clock()})
