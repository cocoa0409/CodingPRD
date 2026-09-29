"""Audits, nonconformities and the corrective action plan loop."""
from datetime import timedelta

from flask import Blueprint

import calc
import common as C
import domain as D
import store as S
import validators as V
from common import add_days, clock_date, clock_now, iso, new_id, now_iso, \
    parse_date_str, parse_iso
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("audits", __name__)

_BLOCKING_AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "REPORT_PENDING")


@bp.post("/audits")
def schedule_audit():
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    holder_id = V.req_id(data, "holder_id")
    auditor_user_id = V.req_str(data, "auditor_user_id", 64)
    audit_type = V.req_enum(data, "audit_type", C.AUDIT_TYPES)
    window_start = V.req_date(data, "window_start")
    window_end = V.req_date(data, "window_end")

    holder = S.holder_or_404(holder_id)
    if not window_end > window_start or window_start < clock_date():
        raise ApiError("ERR_INVALID_AUDIT_WINDOW",
                       "window_end must follow window_start and the window may "
                       "not open in the past")

    for other in ordered(list(S.audits.values())):
        if other["status"] not in _BLOCKING_AUDIT_STATUSES:
            continue
        other_start = parse_date_str(other["window_start"])
        other_end = parse_date_str(other["window_end"])
        if other["auditor_user_id"] == auditor_user_id:
            buffer_days = timedelta(days=C.AUDITOR_TRAVEL_BUFFER_DAYS)
            if (window_start <= other_end + buffer_days
                    and window_end >= other_start - buffer_days):
                raise ApiError("ERR_AUDITOR_WINDOW_CONFLICT",
                               "this auditor already holds an overlapping window")

    for other in ordered(list(S.audits.values())):
        if other["status"] not in _BLOCKING_AUDIT_STATUSES:
            continue
        if other["holder_id"] != holder_id:
            continue
        other_start = parse_date_str(other["window_start"])
        other_end = parse_date_str(other["window_end"])
        if window_start < other_end and other_start < window_end:
            raise ApiError("ERR_HOLDER_AUDIT_WINDOW_CONFLICT",
                           "this holder already has an overlapping audit window")

    audit = {
        "id": new_id(),
        "holder_id": holder_id,
        "auditor_user_id": auditor_user_id,
        "audit_type": audit_type,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "status": "SCHEDULED",
        "nonconformity_count": 0,
        "open_nonconformity_count": 0,
        "started_at": None,
        "closed_at": None,
    }
    S.stamp_new(audit)
    S.audits[audit["id"]] = audit
    D.recompute_next_audit_due(holder)
    touch_once(holder)
    return created(audit)


@bp.post("/audits/<audit_id>/start")
def start_audit(audit_id):
    from auth import authorize
    user_id, role = authorize("Auditor")
    V.body()
    audit = S.audit_or_404(audit_id)
    if user_id != audit["auditor_user_id"]:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID is not this audit's assigned auditor")
    holder = S.holders[audit["holder_id"]]
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "audit status is %s" % audit["status"])
    if clock_date() < parse_date_str(audit["window_start"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the audit window has not opened yet")
    if holder["certificate_status"] not in ("CERTIFIED", "SUSPENDED", "TRANSITIONING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "holder is %s" % holder["certificate_status"])

    audit["status"] = "IN_PROGRESS"
    audit["started_at"] = now_iso()
    touch_once(audit)
    return ok(audit)


@bp.post("/audits/<audit_id>/nonconformities")
def raise_nonconformity(audit_id):
    from auth import authorize
    user_id, role = authorize("Auditor")
    data = V.body()
    clause_code = V.req_str(data, "clause_code", 40)
    grade = V.req_enum(data, "grade", C.GRADES)
    description = V.req_str(data, "description", 1000)
    audit = S.audit_or_404(audit_id)
    if audit["status"] not in ("IN_PROGRESS", "REPORT_PENDING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "audit status is %s" % audit["status"])
    holder = S.holders[audit["holder_id"]]

    # Step one: the score before this finding lands.
    critical, major, minor = calc.grade_counts(S.findings_of_holder(holder["id"]))
    score_before = calc.score_from_counts(critical, major, minor)
    # Step two: allowance multiplier and escalation grace from that score.
    multiplier, grace_days = calc.cap_allowance(score_before)
    # Step three: freeze the deadline on the finding.
    days = calc.cap_deadline_days(grade, multiplier)
    deadline_at = iso(add_days(clock_now(), days))

    finding = {
        "id": new_id(),
        "audit_id": audit["id"],
        "clause_code": clause_code,
        "grade": grade,
        "description": description,
        "status": "OPEN",
        "raised_by_user_id": user_id,
        "compliance_score_at_raise": score_before,
        "deadline_at": deadline_at,
        "escalation_grace_days": grace_days,
        "cap_round": 0,
        "cap_narrative": None,
        "cap_submitted_at": None,
        "cap_reviewed_at": None,
        "closed_at": None,
    }
    S.stamp_new(finding)
    S.nonconformities[finding["id"]] = finding

    if audit["status"] == "IN_PROGRESS":
        audit["status"] = "REPORT_PENDING"
    D.recompute_audit_counts(audit)
    touch_once(audit)
    # Steps four and five: holder counters, score, then the audit cadence.
    D.recompute_holder_aggregates(holder)
    D.recompute_next_audit_due(holder)
    touch_once(holder)
    return created(finding)


@bp.post("/audits/<audit_id>/close")
def close_audit(audit_id):
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    audit = S.audit_or_404(audit_id)
    if audit["status"] not in ("IN_PROGRESS", "REPORT_PENDING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "audit status is %s" % audit["status"])
    if audit["status"] == "REPORT_PENDING" and audit["open_nonconformity_count"] > 0:
        raise ApiError("ERR_AUDIT_HAS_OPEN_NONCONFORMITIES",
                       "%d nonconformities are still open"
                       % audit["open_nonconformity_count"])

    audit["status"] = "CLOSED"
    audit["closed_at"] = now_iso()
    touch_once(audit)
    holder = S.holders[audit["holder_id"]]
    D.recompute_holder_aggregates(holder)
    D.recompute_next_audit_due(holder)
    touch_once(holder)
    return ok(audit)


@bp.post("/nonconformities/<nonconformity_id>/cap-submissions")
def submit_cap(nonconformity_id):
    from auth import authorize
    user_id, role = authorize("ProducerRepresentative")
    data = V.body()
    narrative = V.req_str(data, "narrative", 2000)
    finding = S.nonconformity_or_404(nonconformity_id)
    audit = S.audits[finding["audit_id"]]
    if user_id != audit["holder_id"]:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID is not the audited holder")
    if finding["status"] not in ("OPEN", "CAP_REJECTED", "OVERDUE", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "nonconformity status is %s" % finding["status"])
    if (finding["status"] in ("OVERDUE", "ESCALATED")
            or clock_now() > parse_iso(finding["deadline_at"])):
        raise ApiError("ERR_CAP_DEADLINE_PASSED",
                       "the corrective action deadline has passed")

    finding["status"] = "CAP_SUBMITTED"
    finding["cap_round"] = finding["cap_round"] + 1
    finding["cap_narrative"] = narrative
    finding["cap_submitted_at"] = now_iso()
    touch_once(finding)
    D.recompute_audit_counts(audit)
    return created(finding)


@bp.post("/nonconformities/<nonconformity_id>/cap-review")
def review_cap(nonconformity_id):
    from auth import authorize
    user_id, role = authorize("Auditor", "CertificationOfficer")
    data = V.body()
    decision = V.req_enum(data, "decision", ("ACCEPT", "REJECT"))
    V.opt_str(data, "review_note", 2000)
    finding = S.nonconformity_or_404(nonconformity_id)
    audit = S.audits[finding["audit_id"]]
    if user_id == finding["raised_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the auditor who raised this finding may not review it")
    if finding["status"] != "CAP_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "nonconformity status is %s" % finding["status"])

    finding["cap_reviewed_at"] = now_iso()
    if decision == "REJECT":
        finding["status"] = "CAP_REJECTED"
        touch_once(finding)
    else:
        finding["status"] = "CLOSED"
        finding["closed_at"] = finding["cap_reviewed_at"]
        touch_once(finding)
        D.recompute_audit_counts(audit)
        touch_once(audit)
        holder = S.holders[audit["holder_id"]]
        D.recompute_holder_aggregates(holder)
        D.recompute_next_audit_due(holder)
        touch_once(holder)
    return ok(finding)


@bp.get("/audits/<audit_id>")
def read_audit(audit_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative")
    return ok(S.audit_or_404(audit_id))


@bp.get("/certificate-holders/<holder_id>/audits")
def list_holder_audits(holder_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative")
    status = V.enum_filter("status", C.AUDIT_STATUSES)
    audit_type = V.enum_filter("audit_type", C.AUDIT_TYPES)
    S.holder_or_404(holder_id)
    rows = [a for a in ordered(list(S.audits.values()))
            if a["holder_id"] == holder_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if audit_type:
        rows = [r for r in rows if r["audit_type"] == audit_type]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/nonconformities/<nonconformity_id>")
def read_nonconformity(nonconformity_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative")
    return ok(S.nonconformity_or_404(nonconformity_id))


@bp.get("/audits/<audit_id>/nonconformities")
def list_audit_nonconformities(audit_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative")
    grade = V.enum_filter("grade", C.GRADES)
    status = V.enum_filter("status", C.NC_STATUSES)
    S.audit_or_404(audit_id)
    rows = S.findings_of_audit(audit_id)
    if grade:
        rows = [r for r in rows if r["grade"] == grade]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)
