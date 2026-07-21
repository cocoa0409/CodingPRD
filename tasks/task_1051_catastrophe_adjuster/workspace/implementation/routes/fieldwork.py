from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    require_ctx, ALL_ROLES, get_body, require_fields, require_enum, require_str,
    respond_object, list_response, fetch, base_record, touch, DB, current_clock,
    parse_dt, iso, round_half_up, ApiError,
)

bp = Blueprint("fieldwork", __name__)

INSPECTION_MIN_GAP_MINUTES = 240
ACTIVITIES = {"INSPECTION", "ESTIMATING", "REPORT", "TRAVEL"}
QA_DECISIONS = {"APPROVED", "REVISION_REQUESTED"}


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------
@bp.route("/inspections", methods=["POST"])
def create_inspection():
    require_ctx({"FieldAdjuster"})
    body = get_body()
    require_fields(body, ["assignment_id", "claim_id", "scheduled_start", "scheduled_end"])
    fetch("assignments", body["assignment_id"], "ERR_ASSIGNMENT_NOT_FOUND")
    fetch("claims", body["claim_id"], "ERR_CLAIM_NOT_FOUND")
    try:
        start = parse_dt(body["scheduled_start"])
        end = parse_dt(body["scheduled_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    if not start < end:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scheduled_start must be before scheduled_end")
    # Spacing: >= 240 minutes clearance from every other inspection on same claim.
    gap = timedelta(minutes=INSPECTION_MIN_GAP_MINUTES)
    for other in DB["inspections"].values():
        if other["claim_id"] != body["claim_id"]:
            continue
        o_start = other["_start_dt"]
        o_end = other["_end_dt"]
        if not (start >= o_end + gap or end + gap <= o_start):
            raise ApiError("ERR_INSPECTION_SPACING_CONFLICT", 409)
    rec = base_record()
    rec.update({
        "assignment_id": body["assignment_id"],
        "claim_id": body["claim_id"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "SCHEDULED",
    })
    rec["_start_dt"] = start
    rec["_end_dt"] = end
    DB["inspections"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    require_ctx(ALL_ROLES)
    return list_response("inspections", {
        "assignment_id": request.args.get("assignment_id"),
        "claim_id": request.args.get("claim_id"),
        "status": request.args.get("status"),
    })


@bp.route("/inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("inspections", rid, "ERR_INSPECTION_NOT_FOUND"))


@bp.route("/inspections/<rid>/start", methods=["POST"])
def start_inspection(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    insp = fetch("inspections", rid, "ERR_INSPECTION_NOT_FOUND")
    asn = DB["assignments"][insp["assignment_id"]]
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if insp["status"] not in {"SCHEDULED", "REOPENED"}:
        raise ApiError("ERR_INSPECTION_NOT_SCHEDULED", 409)
    from_scheduled = insp["status"] == "SCHEDULED"
    if from_scheduled:
        if asn["work_status"] != "ACCEPTED":
            raise ApiError("ERR_ASSIGNMENT_NOT_ACCEPTED", 409)
    insp["status"] = "IN_PROGRESS"
    touch(insp)
    if from_scheduled:
        asn["work_status"] = "FIELDWORK"
        touch(asn)
    return respond_object(insp)


@bp.route("/inspections/<rid>/complete", methods=["POST"])
def complete_inspection(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    insp = fetch("inspections", rid, "ERR_INSPECTION_NOT_FOUND")
    asn = DB["assignments"][insp["assignment_id"]]
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if insp["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409)
    insp["status"] = "COMPLETED"
    touch(insp)
    return respond_object(insp)


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------
def _validate_line_items(items):
    if not isinstance(items, list) or len(items) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "line_items must be a non-empty array")
    for li in items:
        if not isinstance(li, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid line item")
        rcv = li.get("rcv_cents")
        dep = li.get("depreciation_pct")
        if isinstance(rcv, bool) or not isinstance(rcv, int) or rcv < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid rcv_cents")
        if isinstance(dep, bool) or not isinstance(dep, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid depreciation_pct")
        if dep < 0 or dep > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "depreciation_pct out of range")


def _compute_estimate(items, policy_type):
    rcv_total = sum(li["rcv_cents"] for li in items)
    acv_total = 0
    for li in items:
        dep = Decimal(str(li["depreciation_pct"]))
        acv_line = round_half_up(Decimal(li["rcv_cents"]) * (Decimal(1) - dep / Decimal(100)))
        acv_total += acv_line
    recoverable = rcv_total - acv_total
    net_payable = acv_total if policy_type == "ACV" else rcv_total
    return rcv_total, acv_total, recoverable, net_payable


@bp.route("/estimates", methods=["POST"])
def create_estimate():
    require_ctx({"FieldAdjuster"})
    body = get_body()
    require_fields(body, ["inspection_id", "claim_id", "line_items"])
    fetch("inspections", body["inspection_id"], "ERR_INSPECTION_NOT_FOUND")
    claim = fetch("claims", body["claim_id"], "ERR_CLAIM_NOT_FOUND")
    _validate_line_items(body["line_items"])
    rcv_total, acv_total, recoverable, net_payable = _compute_estimate(
        body["line_items"], claim["policy_type"])
    rec = base_record()
    rec.update({
        "inspection_id": body["inspection_id"],
        "claim_id": body["claim_id"],
        "line_items": body["line_items"],
        "rcv_total_cents": rcv_total,
        "acv_total_cents": acv_total,
        "recoverable_depreciation_cents": recoverable,
        "net_payable_cents": net_payable,
        "status": "DRAFT",
    })
    DB["estimates"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/estimates", methods=["GET"])
def list_estimates():
    require_ctx(ALL_ROLES)
    return list_response("estimates", {
        "inspection_id": request.args.get("inspection_id"),
        "claim_id": request.args.get("claim_id"),
        "status": request.args.get("status"),
    })


@bp.route("/estimates/<rid>", methods=["GET"])
def get_estimate(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("estimates", rid, "ERR_ESTIMATE_NOT_FOUND"))


def _recompute_claim_rcv(claim_id):
    """Claim.rcv_cents := rcv_total of the APPROVED estimate with the latest
    created_at (tie-break: latest updated_at, then insertion seq — never id)."""
    approved = [e for e in DB["estimates"].values()
                if e["claim_id"] == claim_id and e["status"] == "APPROVED"]
    if not approved:
        return
    chosen = max(approved, key=lambda e: (e["created_at"], e["updated_at"], e["_seq"]))
    claim = DB["claims"][claim_id]
    claim["rcv_cents"] = chosen["rcv_total_cents"]
    touch(claim)


@bp.route("/estimates/<rid>/approve", methods=["POST"])
def approve_estimate(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    est = fetch("estimates", rid, "ERR_ESTIMATE_NOT_FOUND")
    insp = DB["inspections"][est["inspection_id"]]
    asn = DB["assignments"][insp["assignment_id"]]
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if est["status"] != "DRAFT":
        raise ApiError("ERR_ESTIMATE_NOT_DRAFT", 409)
    if insp["status"] != "COMPLETED":
        raise ApiError("ERR_INSPECTION_NOT_COMPLETED", 409)
    est["status"] = "APPROVED"
    touch(est)
    _recompute_claim_rcv(est["claim_id"])
    return respond_object(est)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
@bp.route("/reports", methods=["POST"])
def create_report():
    require_ctx({"FieldAdjuster"})
    body = get_body()
    require_fields(body, ["inspection_id", "assignment_id", "scope_narrative"])
    fetch("inspections", body["inspection_id"], "ERR_INSPECTION_NOT_FOUND")
    fetch("assignments", body["assignment_id"], "ERR_ASSIGNMENT_NOT_FOUND")
    require_str(body["scope_narrative"], "scope_narrative")
    photo_count = body.get("photo_count", 0)
    if photo_count is None:
        photo_count = 0
    if isinstance(photo_count, bool) or not isinstance(photo_count, int) or photo_count < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid photo_count")
    rec = base_record()
    rec.update({
        "inspection_id": body["inspection_id"],
        "assignment_id": body["assignment_id"],
        "scope_narrative": body["scope_narrative"],
        "photo_count": photo_count,
        "qa_reviewer_id": None,
        "qa_decision": None,
        "qa_notes": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    DB["reports"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/reports", methods=["GET"])
def list_reports():
    require_ctx(ALL_ROLES)
    return list_response("reports", {
        "inspection_id": request.args.get("inspection_id"),
        "assignment_id": request.args.get("assignment_id"),
        "status": request.args.get("status"),
    })


@bp.route("/reports/<rid>", methods=["GET"])
def get_report(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("reports", rid, "ERR_REPORT_NOT_FOUND"))


def _report_forward_side_effects(rep):
    asn = DB["assignments"][rep["assignment_id"]]
    if asn["work_status"] == "FIELDWORK":
        asn["work_status"] = "WORK_COMPLETE"
        touch(asn)
    claim = DB["claims"][asn["claim_id"]]
    if claim["status"] == "IN_PROGRESS":
        claim["status"] = "UNDER_REVIEW"
        touch(claim)


@bp.route("/reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    rep = fetch("reports", rid, "ERR_REPORT_NOT_FOUND")
    asn = DB["assignments"][rep["assignment_id"]]
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if rep["status"] not in {"DRAFT", "REVISION_REQUESTED"}:
        raise ApiError("ERR_REPORT_NOT_SUBMITTABLE", 409)
    insp = DB["inspections"][rep["inspection_id"]]
    if insp["status"] != "COMPLETED":
        raise ApiError("ERR_INSPECTION_NOT_COMPLETED", 409)
    has_approved_estimate = any(
        e["inspection_id"] == rep["inspection_id"] and e["status"] == "APPROVED"
        for e in DB["estimates"].values())
    if not has_approved_estimate:
        raise ApiError("ERR_ESTIMATE_NOT_APPROVED", 409)
    if rep["photo_count"] < 1:
        raise ApiError("ERR_REPORT_NO_PHOTOS", 422)
    rep["status"] = "SUBMITTED"
    touch(rep)
    _report_forward_side_effects(rep)
    return respond_object(rep)


@bp.route("/reports/<rid>/qa-decision", methods=["POST"])
def qa_decision(rid):
    uid, role = require_ctx({"QAReviewer"})
    rep = fetch("reports", rid, "ERR_REPORT_NOT_FOUND")
    asn = DB["assignments"][rep["assignment_id"]]
    # Segregation of duties (priority 4) before state.
    if uid == asn["adjuster_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    if rep["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_IN_REVIEW", 409)
    body = get_body()
    decision = body.get("decision")
    if decision not in QA_DECISIONS:
        raise ApiError("ERR_INVALID_DECISION", 400)
    qa_notes = body.get("qa_notes")
    rep["qa_reviewer_id"] = uid
    rep["qa_decision"] = decision
    rep["qa_notes"] = qa_notes
    if decision == "APPROVED":
        rep["status"] = "APPROVED"
        touch(rep)
        claim = DB["claims"][asn["claim_id"]]
        if claim["status"] == "UNDER_REVIEW":
            claim["status"] = "SETTLED"
            touch(claim)
    else:  # REVISION_REQUESTED
        rep["revision_count"] += 1
        rep["status"] = "REVISION_REQUESTED"
        touch(rep)
        # three-hop revert cascade
        insp = DB["inspections"][rep["inspection_id"]]
        if insp["status"] == "COMPLETED":
            insp["status"] = "REOPENED"
            touch(insp)
        if asn["work_status"] == "WORK_COMPLETE":
            asn["work_status"] = "FIELDWORK"
            touch(asn)
        claim = DB["claims"][asn["claim_id"]]
        if claim["status"] == "UNDER_REVIEW":
            claim["status"] = "IN_PROGRESS"
            touch(claim)
    return respond_object(rep)


# ---------------------------------------------------------------------------
# TimeEntry (immutable ledger row: id + created_at only)
# ---------------------------------------------------------------------------
@bp.route("/time-entries", methods=["POST"])
def create_time_entry():
    require_ctx({"FieldAdjuster"})
    body = get_body()
    require_fields(body, ["assignment_id", "work_date", "activity", "hours"])
    fetch("assignments", body["assignment_id"], "ERR_ASSIGNMENT_NOT_FOUND")
    try:
        parse_dt(body["work_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid work_date")
    require_enum(body["activity"], ACTIVITIES, "activity")
    hours = body["hours"]
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hours must be > 0")
    expense = body.get("expense_cents", 0)
    if expense is None:
        expense = 0
    if isinstance(expense, bool) or not isinstance(expense, int) or expense < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid expense_cents")
    rec = base_record(with_version=False)
    rec.update({
        "assignment_id": body["assignment_id"],
        "work_date": body["work_date"],
        "activity": body["activity"],
        "hours": hours,
        "expense_cents": expense,
    })
    DB["time_entries"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/time-entries", methods=["GET"])
def list_time_entries():
    require_ctx(ALL_ROLES)
    return list_response("time_entries", {
        "assignment_id": request.args.get("assignment_id"),
        "activity": request.args.get("activity"),
    })


@bp.route("/time-entries/<rid>", methods=["GET"])
def get_time_entry(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("time_entries", rid, "ERR_TIME_ENTRY_NOT_FOUND"))
