"""Routes: incidents and compliance cases."""

from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_LATE_REPORT, ERR_LATE_CORRECTION_PLAN,
)
from util import (
    ok_object, ok_list, paginate, require_roles, get_or_404, body,
    need_str, need_enum, need_ts, stamp_new, touch, pub, sort_created,
    fmt_ts, now_ts, opt_ts,
)
from logic import recompute_home_counters

bp = Blueprint("routes_d", __name__)

ALL = ("Provider", "Nurse", "CaregiverRole")
PROVIDER = ("Provider",)
PROVIDER_NURSE = ("Provider", "Nurse")

INCIDENT_TYPES = ("FALL", "MED_ERROR", "ELOPEMENT", "ABUSE_ALLEGATION", "INJURY")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
ABUSE_CITATION_PREFIX = "WAC388-76-10"
REPORT_DEADLINE_MINUTES = 24 * 60


def _linked_case(incident_id):
    for c in db.cases.values():
        if c["incident_id"] == incident_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@bp.post("/api/incidents")
@require_roles(*ALL)
def create_incident():
    b = body()
    resident = get_or_404(db.residents, b.get("resident_id"), "resident") \
        if "resident_id" in b else None
    # structural
    resident_id = need_str(b, "resident_id")
    incident_type = need_enum(b, "incident_type", INCIDENT_TYPES)
    severity = need_enum(b, "severity", SEVERITIES)
    occurred_dt = need_ts(b, "occurred_at")
    description = need_str(b, "description")
    now = db.now()
    delay_minutes = int((now - occurred_dt).total_seconds() // 60)
    late = severity in ("MAJOR", "CRITICAL") and delay_minutes > REPORT_DEADLINE_MINUTES
    rec = stamp_new({
        "resident_id": resident_id,
        "incident_type": incident_type,
        "severity": severity,
        "occurred_at": fmt_ts(occurred_dt),
        "_occurred_dt": occurred_dt,
        "reported_at": fmt_ts(now),
        "_reported_dt": now,
        "description": description,
        "status": "REPORTED",
        "_late": late,
    })
    db.incidents[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/incidents")
@require_roles(*PROVIDER_NURSE)
def list_incidents():
    items = sort_created(list(db.incidents.values()))
    for f in ("resident_id", "status", "severity"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if i.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(i) for i in page], meta)


@bp.get("/api/incidents/<id>")
@require_roles(*PROVIDER_NURSE)
def get_incident(id):
    rec = get_or_404(db.incidents, id, "incident")
    return ok_object(pub(rec))


@bp.post("/api/incidents/<id>/open-case")
@require_roles(*PROVIDER)
def open_case(id):
    inc = get_or_404(db.incidents, id, "incident")
    if inc["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "incident is not REPORTED")
    if inc["severity"] not in ("MAJOR", "CRITICAL"):
        raise_err(ERR_INVALID_STATE, "MINOR incidents never open state cases")
    existing = _linked_case(id)
    if inc.get("_late"):
        raise_err(ERR_LATE_REPORT,
                  "incident was filed more than 24h after occurred_at")
    if existing is not None and existing["status"] == "OPEN":
        # Reopen cycle: the case stayed OPEN through the incident's
        # UNDER_REVIEW -> REPORTED reset (PRD §3.6). There is exactly one case
        # per incident, so re-link the existing OPEN case rather than create a
        # duplicate; the incident re-enters UNDER_REVIEW.
        inc["status"] = "UNDER_REVIEW"
        touch(inc)
        return ok_object(pub(existing), 201)
    if existing is not None and existing["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, "a live compliance case already exists for the incident")
    inc["status"] = "UNDER_REVIEW"
    touch(inc)
    resident = db.residents.get(inc["resident_id"])
    home_id = resident["home_id"] if resident else None
    case = stamp_new({
        "home_id": home_id,
        "incident_id": id,
        "citation_code": None,
        "correction_plan_due_at": None,
        "correction_plan_submitted_at": None,
        "status": "OPEN",
    })
    db.cases[case["id"]] = case
    home = db.homes.get(home_id)
    if home is not None:
        recompute_home_counters(home)
    return ok_object(pub(case), 201)


@bp.post("/api/incidents/<id>/reopen")
@require_roles(*PROVIDER)
def reopen_incident(id):
    inc = get_or_404(db.incidents, id, "incident")
    if inc["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "incident is not UNDER_REVIEW")
    case = _linked_case(id)
    if case is None or case["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "linked compliance case is not OPEN")
    inc["status"] = "REPORTED"
    touch(inc)
    return ok_object(pub(inc))


@bp.post("/api/incidents/<id>/close")
@require_roles(*PROVIDER)
def close_incident(id):
    inc = get_or_404(db.incidents, id, "incident")
    if inc["status"] != "RESOLVED":
        raise_err(ERR_INVALID_STATE, "incident is not RESOLVED")
    case = _linked_case(id)
    if case is None or case["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, "linked compliance case is not CLOSED")
    inc["status"] = "CLOSED"
    touch(inc)
    return ok_object(pub(inc))


@bp.post("/api/incidents/<id>/close-minor")
@require_roles(*PROVIDER)
def close_minor_incident(id):
    inc = get_or_404(db.incidents, id, "incident")
    if inc["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "incident is not REPORTED")
    if inc["severity"] != "MINOR":
        raise_err(ERR_INVALID_STATE, "only MINOR incidents close directly")
    inc["status"] = "CLOSED"
    touch(inc)
    return ok_object(pub(inc))


# ---------------------------------------------------------------------------
# Compliance cases
# ---------------------------------------------------------------------------

@bp.get("/api/compliance-cases")
@require_roles(*PROVIDER_NURSE)
def list_cases():
    items = sort_created(list(db.cases.values()))
    for f in ("home_id", "incident_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(c) for c in page], meta)


@bp.get("/api/compliance-cases/<id>")
@require_roles(*PROVIDER_NURSE)
def get_case(id):
    rec = get_or_404(db.cases, id, "compliance case")
    return ok_object(pub(rec))


@bp.post("/api/compliance-cases/<id>/substantiate")
@require_roles(*PROVIDER)
def substantiate_case(id):
    case = get_or_404(db.cases, id, "compliance case")
    if case["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "compliance case is not OPEN")
    citation = need_str(body(), "citation_code")
    now = db.now()
    case["status"] = "SUBSTANTIATED"
    case["citation_code"] = citation
    case["correction_plan_due_at"] = fmt_ts(now + timedelta(days=14))
    touch(case)
    inc = db.incidents.get(case["incident_id"])
    if inc is not None and inc["status"] in ("REPORTED", "UNDER_REVIEW"):
        inc["status"] = "RESOLVED"
        touch(inc)
    home = db.homes.get(case["home_id"])
    if home is not None:
        recompute_home_counters(home)
        if citation.startswith(ABUSE_CITATION_PREFIX) and home["status"] == "LICENSED":
            home["status"] = "SUSPENDED"
            touch(home)
    return ok_object(pub(case))


@bp.post("/api/compliance-cases/<id>/mark-unfounded")
@require_roles(*PROVIDER)
def unfound_case(id):
    case = get_or_404(db.cases, id, "compliance case")
    if case["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "compliance case is not OPEN")
    case["status"] = "UNFOUNDED"
    touch(case)
    inc = db.incidents.get(case["incident_id"])
    if inc is not None and inc["status"] in ("REPORTED", "UNDER_REVIEW"):
        inc["status"] = "RESOLVED"
        touch(inc)
    home = db.homes.get(case["home_id"])
    if home is not None:
        recompute_home_counters(home)
    return ok_object(pub(case))


@bp.post("/api/compliance-cases/<id>/close")
@require_roles(*PROVIDER)
def close_case(id):
    case = get_or_404(db.cases, id, "compliance case")
    if case["status"] not in ("SUBSTANTIATED", "UNFOUNDED"):
        raise_err(ERR_INVALID_STATE,
                  "compliance case is not SUBSTANTIATED or UNFOUNDED")
    b = body()
    if case["status"] == "SUBSTANTIATED":
        submitted = opt_ts(b, "correction_plan_submitted_at")
        if submitted is None:
            raise_err(ERR_LATE_CORRECTION_PLAN, "correction_plan_submitted_at is required")
        due = None
        if case.get("correction_plan_due_at"):
            from util import parse_ts
            due = parse_ts(case["correction_plan_due_at"])
        if due is not None and submitted > due:
            raise_err(ERR_LATE_CORRECTION_PLAN,
                      "correction plan submitted after correction_plan_due_at")
        case["correction_plan_submitted_at"] = fmt_ts(submitted)
    case["status"] = "CLOSED"
    touch(case)
    home = db.homes.get(case["home_id"])
    if home is not None:
        recompute_home_counters(home)
    return ok_object(pub(case))
