"""Transparency reporting and the logical clock (PRD §3.9, §2.4)."""

from flask import Blueprint

import ser
from core import (
    APPEAL_OPEN, APPEAL_TERMINAL, REPORT_VARIANTS, base_fields, body, created,
    db, dec, div4, fail, fmt_ts, now, now_iso, ok, parse_iso, req_enum, req_ts,
    require, round4, touch,
)
from svc import find

bp = Blueprint("reports", __name__)


@bp.post("/transparency-reports")
def open_report():
    require("TrustSafetyAdmin")
    payload = body()
    period_start = req_ts(payload, "period_start")
    period_end = req_ts(payload, "period_end")

    if not period_end > period_start:
        fail("ERR_REPORT_PERIOD_INVALID", "period_end must be strictly after period_start.")
    for existing in db.transparency_reports.values():
        other_start = parse_iso(existing["period_start"])
        other_end = parse_iso(existing["period_end"])
        # Closed intervals: sharing a single endpoint instant is an intersection.
        if period_start <= other_end and other_start <= period_end:
            fail("ERR_REPORT_PERIOD_OVERLAP",
                 "The requested period intersects an existing report's period.")

    record = {
        "period_start": fmt_ts(period_start),
        "period_end": fmt_ts(period_end),
        "variant": None,
        "enforcement_volume": 0,
        "removal_volume": 0,
        "age_gate_volume": 0,
        "warn_volume": 0,
        "overturn_adjusted_volume": 0,
        "appeal_count": 0,
        "appeal_overturn_rate": round4(0),
        "category_rate_breakdown": [],
        "legal_request_count": 0,
        "legal_grant_rate": round4(0),
        "computed_at": None,
        "published_at": None,
        "status": "DRAFT",
    }
    base_fields(record)
    db.transparency_reports[record["id"]] = record
    return created(ser.transparency_report(record))


def _window_cases(report):
    start = parse_iso(report["period_start"])
    end = parse_iso(report["period_end"])
    window = []
    for case in db.moderation_cases.values():
        if case["status"] != "DECIDED" or not case.get("decided_at"):
            continue
        decided = parse_iso(case["decided_at"])
        if decided is None or decided < start or decided > end:
            continue
        window.append(case)
    return window


def _category_code_of(case):
    version = db.policy_versions.get(case.get("policy_version_id"))
    if version is None:
        return None
    category = db.policy_categories.get(version["policy_category_id"])
    return category["code"] if category else None


@bp.post("/transparency-reports/<report_id>/compute")
def compute_report(report_id):
    require("TrustSafetyAdmin")
    payload = body()
    variant = req_enum(payload, "variant", REPORT_VARIANTS)

    report = find(db.transparency_reports, report_id, "ERR_REPORT_NOT_FOUND")
    if report["status"] == "PUBLISHED":
        fail("ERR_REPORT_ALREADY_PUBLISHED", "A published report cannot be recomputed.")

    window = _window_cases(report)
    base = window if variant == "PROVISIONAL" else [
        case for case in window if not case.get("is_overturned")]

    report["enforcement_volume"] = len(base)
    report["removal_volume"] = len([c for c in base if c.get("decision_outcome") == "REMOVE"])
    report["age_gate_volume"] = len([c for c in base if c.get("decision_outcome") == "AGE_GATE"])
    report["warn_volume"] = len([c for c in base if c.get("decision_outcome") == "WARN"])
    report["overturn_adjusted_volume"] = len(
        [c for c in window if not c.get("is_overturned")])

    window_ids = {c["id"]: c for c in window}
    terminal_by_code = {}
    open_count = 0
    for appeal in db.appeals.values():
        case = window_ids.get(appeal["case_id"])
        if case is None:
            continue
        if appeal["status"] in APPEAL_TERMINAL:
            code = _category_code_of(case)
            if code is None:
                continue
            row = terminal_by_code.setdefault(code, {"appealed": 0, "overturned": 0})
            row["appealed"] += 1
            if appeal["status"] == "OVERTURNED":
                row["overturned"] += 1
        elif appeal["status"] in APPEAL_OPEN:
            open_count += 1

    breakdown = []
    for code in sorted(terminal_by_code):
        row = terminal_by_code[code]
        # Per-category rounding happens FIRST, before the mean.
        rate = div4(row["overturned"], row["appealed"])
        breakdown.append({
            "category_code": code,
            "appealed": row["appealed"],
            "overturned": row["overturned"],
            "rate": rate,
        })
    report["category_rate_breakdown"] = breakdown
    if breakdown:
        total = sum((row["rate"] for row in breakdown), dec(0))
        report["appeal_overturn_rate"] = round4(total / dec(len(breakdown)))
    else:
        report["appeal_overturn_rate"] = round4(0)

    terminal_count = sum(row["appealed"] for row in terminal_by_code.values())
    report["appeal_count"] = (terminal_count + open_count if variant == "PROVISIONAL"
                              else terminal_count)

    legal = [c for c in window if c.get("origin") == "LEGAL_REQUEST"]
    report["legal_request_count"] = len(legal)
    if legal:
        granted = len([c for c in legal if c.get("decision_outcome") == "REMOVE"])
        report["legal_grant_rate"] = div4(granted, len(legal))
    else:
        report["legal_grant_rate"] = round4(0)

    report["variant"] = variant
    report["computed_at"] = now_iso()
    report["status"] = "COMPUTED"
    touch(report)
    return ok(ser.transparency_report(report))


@bp.post("/transparency-reports/<report_id>/publish")
def publish_report(report_id):
    require("TrustSafetyAdmin", "LegalCounsel")
    report = find(db.transparency_reports, report_id, "ERR_REPORT_NOT_FOUND")

    # PRD §3.9: a PUBLISHED report can neither be recomputed nor republished, and
    # both attempts yield ERR_REPORT_ALREADY_PUBLISHED.
    if report["status"] == "PUBLISHED":
        fail("ERR_REPORT_ALREADY_PUBLISHED", "This report is already published.")
    if report["status"] != "COMPUTED":
        fail("ERR_REPORT_NOT_COMPUTED", "Only a COMPUTED report can be published.")
    if report.get("variant") != "RESTATED":
        fail("ERR_REPORT_NOT_RESTATED", "Only a RESTATED report may be published.")

    window_ids = {c["id"] for c in _window_cases(report)}
    for appeal in db.appeals.values():
        if appeal["case_id"] in window_ids and appeal["status"] in APPEAL_OPEN:
            fail("ERR_OPEN_APPEALS_IN_PERIOD",
                 "An appeal on a case decided inside the period is still open.")

    report["published_at"] = now_iso()
    report["status"] = "PUBLISHED"
    touch(report)
    return ok(ser.transparency_report(report))


@bp.get("/transparency-reports/<report_id>")
def get_report(report_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "LegalCounsel")
    record = find(db.transparency_reports, report_id, "ERR_REPORT_NOT_FOUND")
    return ok(ser.transparency_report(record))


@bp.post("/_clock/set_current_utc")
def set_clock():
    require("TrustSafetyAdmin")
    payload = body()
    target = req_ts(payload, "to_iso8601")
    if target < now():
        fail("ERR_CLOCK_NOT_MONOTONIC", "The logical clock may only move forward or stay put.")
    db.clock.set(target)
    return ok({"current_utc": now_iso()})
