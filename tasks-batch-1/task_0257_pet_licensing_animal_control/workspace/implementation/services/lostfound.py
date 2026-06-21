"""LostFoundReport state machine + reciprocal matching (PRD §3.8, SCAFFOLD §1.2).

States: OPEN, MATCHED, RESOLVED, CLOSED. (CLOSED terminal.)
"""
from db import db
from errors import err
from services import calc
from services.core import append_audit, parse_iso, touch


def _actor():
    from flask import request
    return request.headers.get("X-User-Role", "")


def _opposite(report_type):
    return "FOUND" if report_type == "LOST" else "LOST"


def match(report):
    if report["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Report is not OPEN.")

    opposite = _opposite(report["report_type"])
    best = None
    best_score = -1
    best_key = None
    for cand in db.lost_found_reports.values():
        if cand["id"] == report["id"]:
            continue
        if cand["report_type"] != opposite or cand["status"] != "OPEN":
            continue
        score = calc.match_score(report, cand)
        if score < calc.MATCH_MIN_SCORE:
            continue
        # tie-break: higher score, then earlier reported_at, then earlier created_at
        key = (-score, parse_iso(cand["reported_at"]), cand["created_at"])
        if best is None or key < best_key:
            best = cand
            best_score = score
            best_key = key

    if best is None:
        raise err("ERR_NO_MATCH_CANDIDATE", "No counterpart report meets the score floor.")

    report["matched_report_id"] = best["id"]
    report["match_score"] = best_score
    report["status"] = "MATCHED"
    touch(report)

    best["matched_report_id"] = report["id"]
    best["match_score"] = best_score
    best["status"] = "MATCHED"
    touch(best)

    append_audit("LOST_FOUND_REPORT", report["id"], "REPORTS_MATCHED", _actor())


def resolve(report):
    if report["status"] != "MATCHED":
        raise err("ERR_INVALID_STATE", "Report is not MATCHED.")
    report["status"] = "RESOLVED"
    touch(report)
    counterpart = db.lost_found_reports.get(report.get("matched_report_id"))
    if counterpart is not None:
        counterpart["status"] = "RESOLVED"
        touch(counterpart)
    append_audit("LOST_FOUND_REPORT", report["id"], "REPORT_RESOLVED", _actor())


def unmatch(report):
    if report["status"] != "MATCHED":
        raise err("ERR_INVALID_STATE", "Report is not MATCHED.")
    counterpart = db.lost_found_reports.get(report.get("matched_report_id"))
    report["matched_report_id"] = None
    report["match_score"] = 0
    report["status"] = "OPEN"
    touch(report)
    if counterpart is not None:
        counterpart["matched_report_id"] = None
        counterpart["match_score"] = 0
        counterpart["status"] = "OPEN"
        touch(counterpart)
    append_audit("LOST_FOUND_REPORT", report["id"], "REPORTS_UNMATCHED", _actor())


def close(report):
    if report["status"] not in ("OPEN", "RESOLVED"):
        raise err("ERR_INVALID_STATE", "Report is not OPEN or RESOLVED.")
    report["status"] = "CLOSED"
    touch(report)
    append_audit("LOST_FOUND_REPORT", report["id"], "REPORT_CLOSED", _actor())
