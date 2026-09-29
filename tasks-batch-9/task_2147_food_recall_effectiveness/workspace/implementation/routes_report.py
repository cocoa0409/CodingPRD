"""Public warnings and status reports."""
from flask import Blueprint, request

from core import (ALL_ROLES, ROLE_COORD, ROLE_FIRM, auth, body, created, db, err, new_row,
                  now_iso, ok, opt_enum, opt_str, paginate, parse_iso, public, req_datetime,
                  req_enum, req_str, upd)
from domain import (REPORT_KINDS, REPORT_REJECT_EXTENSION_DAYS, WARNING_TYPES, add_days,
                    apply_metrics, iso, next_period_index, recall_children)
from resolve import (firm_scope, get_recall, get_sub, not_terminated, recall_state, sub_recall,
                     sync)

bp = Blueprint("report", __name__)


# ------------------------------------------------------------------ public warnings
@bp.post("/recalls/<recall_id>/public-warnings")
def create_warning(recall_id):
    user_id, role = auth([ROLE_COORD])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    warning_type = req_enum(data, "warning_type", WARNING_TYPES)
    headline = req_str(data, "headline")
    text = req_str(data, "body")
    not_terminated(recall)
    sync(recall)
    warning = new_row(db.public_warnings,
                      recall_id=recall["id"],
                      warning_type=warning_type,
                      headline=headline,
                      body=text,
                      drafted_by_user_id=user_id,
                      reviewed_by_user_id=None,
                      status="DRAFT",
                      reject_count=0,
                      review_note=None,
                      published_at=None)
    return created(public(warning))


@bp.get("/recalls/<recall_id>/public-warnings")
def list_warnings(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.public_warnings, recall["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows)


@bp.post("/public-warnings/<warning_id>/submit")
def submit_warning(warning_id):
    user_id, role = auth([ROLE_COORD])
    warning = get_sub(db.public_warnings, warning_id)
    recall = sub_recall(warning)
    firm_scope(role, user_id, recall)
    recall_state(recall, ("CLASSIFIED", "NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING",
                          "EFFECTIVENESS_REVIEW", "TERMINATION_REQUESTED"))       # rung 11
    if warning.get("status") != "DRAFT":                                          # rung 13
        err("ERR_INVALID_WARNING_STATE",
            "Warning status %s does not permit submission" % warning.get("status"))
    sync(recall)
    upd(warning, status="IN_REVIEW")
    return ok(public(warning))


@bp.post("/public-warnings/<warning_id>/review")
def review_warning(warning_id):
    user_id, role = auth([ROLE_COORD])
    warning = get_sub(db.public_warnings, warning_id)
    recall = sub_recall(warning)
    firm_scope(role, user_id, recall)
    data = body()
    decision = req_enum(data, "decision", {"APPROVE", "REJECT"})
    review_note = opt_str(data, "review_note")
    not_terminated(recall)                                                        # rung 11
    if warning.get("status") != "IN_REVIEW":                                      # rung 13
        err("ERR_INVALID_WARNING_STATE",
            "Warning status %s does not permit review" % warning.get("status"))
    if user_id == warning.get("drafted_by_user_id"):                              # rung 22
        err("ERR_SEGREGATION_OF_DUTIES",
            "A coordinator may not review their own draft")
    sync(recall)
    if review_note is not None:
        upd(warning, review_note=review_note)
    upd(warning, reviewed_by_user_id=user_id)
    if decision == "APPROVE":
        upd(warning, status="APPROVED")
    else:
        upd(warning, status="DRAFT",
            reject_count=int(warning.get("reject_count") or 0) + 1)
    return ok(public(warning))


@bp.post("/public-warnings/<warning_id>/publish")
def publish_warning(warning_id):
    user_id, role = auth([ROLE_COORD])
    warning = get_sub(db.public_warnings, warning_id)
    recall = sub_recall(warning)
    firm_scope(role, user_id, recall)
    not_terminated(recall)                                                        # rung 11
    if warning.get("status") != "APPROVED":                                       # rung 13
        err("ERR_INVALID_WARNING_STATE",
            "Warning status %s does not permit publication" % warning.get("status"))
    if warning.get("warning_type") in ("PRESS_RELEASE", "PUBLIC_WARNING") and \
            recall.get("hazard_class") not in ("CLASS_I", "CLASS_II"):            # rung 21
        err("ERR_PUBLIC_WARNING_NOT_WARRANTED",
            "This hazard class does not warrant a broad public communication")
    sync(recall)
    upd(warning, status="PUBLISHED", published_at=now_iso())
    return ok(public(warning))


# ------------------------------------------------------------------ status reports
@bp.post("/recalls/<recall_id>/status-reports")
def create_report(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    report_kind = opt_enum(data, "report_kind", REPORT_KINDS, default="INTERIM")
    start_raw, start_dt = req_datetime(data, "period_start")
    end_raw, end_dt = req_datetime(data, "period_end")
    if not start_dt < end_dt:
        err("ERR_INVALID_REQUEST", "period_start must be strictly earlier than period_end")
    not_terminated(recall)                                                        # rung 11
    sync(recall)
    for existing in recall_children(db.status_reports, recall["id"]):             # rung 26
        other_start = parse_iso(existing.get("period_start"))
        other_end = parse_iso(existing.get("period_end"))
        if other_start is None or other_end is None:
            continue
        if start_dt < other_end and other_start < end_dt:
            err("ERR_REPORT_PERIOD_OVERLAP",
                "The window overlaps an existing status report window")
    report = new_row(db.status_reports,
                     recall_id=recall["id"],
                     period_index=next_period_index(recall["id"]),
                     report_kind=report_kind,
                     period_start=start_raw,
                     period_end=end_raw,
                     due_at=end_raw,
                     status="PENDING",
                     submitted_at=None,
                     narrative=None,
                     reported_effectiveness_pct=0,
                     reject_count=0,
                     adjudication_note=None)
    return created(public(report))


@bp.get("/recalls/<recall_id>/status-reports")
def list_reports(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.status_reports, recall["id"])
    for field in ("status", "report_kind"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return paginate(rows)


@bp.post("/status-reports/<report_id>/submit")
def submit_report(report_id):
    user_id, role = auth([ROLE_FIRM])
    report = get_sub(db.status_reports, report_id)
    recall = sub_recall(report)
    firm_scope(role, user_id, recall)
    data = body()
    narrative = req_str(data, "narrative")
    not_terminated(recall)                                                        # rung 11
    if report.get("status") not in ("PENDING", "OVERDUE"):                        # rung 17
        err("ERR_INVALID_REPORT_STATE",
            "Report status %s does not permit submission" % report.get("status"))
    sync(recall)
    upd(report, status="SUBMITTED", submitted_at=now_iso(), narrative=narrative,
        reported_effectiveness_pct=recall.get("official_effectiveness_pct"))
    return ok(public(report))


@bp.post("/status-reports/<report_id>/adjudicate")
def adjudicate_report(report_id):
    user_id, role = auth([ROLE_COORD])
    report = get_sub(db.status_reports, report_id)
    recall = sub_recall(report)
    firm_scope(role, user_id, recall)
    data = body()
    decision = req_enum(data, "decision", {"ACCEPT", "REJECT"})
    adjudication_note = opt_str(data, "adjudication_note")
    not_terminated(recall)                                                        # rung 11
    if report.get("status") != "SUBMITTED":                                       # rung 17
        err("ERR_INVALID_REPORT_STATE",
            "Report status %s does not permit adjudication" % report.get("status"))
    sync(recall)
    if adjudication_note is not None:
        upd(report, adjudication_note=adjudication_note)
    if decision == "ACCEPT":
        upd(report, status="ACCEPTED")
    else:
        due = parse_iso(report.get("due_at"))
        new_due = iso(add_days(due, REPORT_REJECT_EXTENSION_DAYS)) if due else report.get("due_at")
        upd(report, status="PENDING",
            reject_count=int(report.get("reject_count") or 0) + 1,
            submitted_at=None, narrative=None,
            due_at=new_due, period_end=new_due)
    return ok(public(report))
