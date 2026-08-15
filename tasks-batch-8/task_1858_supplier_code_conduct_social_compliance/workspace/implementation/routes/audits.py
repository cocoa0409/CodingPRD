"""Audit endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_SUPPLIER_NOT_AUDITABLE,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_AUDITOR_NOT_ACTIVE,
    ERR_AUDITOR_COUNTRY_NOT_COVERED,
    ERR_AUDIT_ALREADY_OPEN,
    ERR_COVERED_BY_MUTUAL_RECOGNITION,
    ERR_AUDITOR_BOOKING_CONFLICT,
    ERR_FACILITY_AUDIT_GAP_VIOLATION,
    ERR_INVALID_AUDIT_WINDOW,
    ERR_AUDIT_WINDOW_NOT_OPEN,
    ERR_AUDIT_INVALID_STATE,
    ERR_INTERVIEW_RECORD_MISSING,
    ERR_CRITICAL_GRIEVANCE_UNRESOLVED,
)
from services.utils import new_uuid, parse_iso, to_iso_ms
from services.scorecard import (
    recompute_facility_risk,
    recompute_supplier_scorecard,
    find_supplier_for_audit,
    PROGRAM_VALIDITY_MONTHS,
    _valid_accepted_claim_for_facility,
)

bp = Blueprint("audits", __name__)

AUDIT_TYPES = {"INITIAL", "ANNUAL", "RE_AUDIT", "FOLLOW_UP"}
ANNOUNCEMENTS = {"ANNOUNCED", "SEMI_ANNOUNCED"}


def serialize(a):
    return {
        "id": a["id"],
        "facility_id": a["facility_id"],
        "auditor_id": a["auditor_id"],
        "audit_type": a["audit_type"],
        "announcement": a["announcement"],
        "scheduled_start": a["scheduled_start"],
        "scheduled_end": a["scheduled_end"],
        "status": a["status"],
        "zt_count": a["zt_count"],
        "major_count": a["major_count"],
        "minor_count": a["minor_count"],
        "cancel_reason": a.get("cancel_reason"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/audits", methods=["POST"])
def create_audit():
    require_roles("AuditCoordinator")
    body = request.get_json(silent=True) or {}
    facility_id = body.get("facility_id")
    auditor_id = body.get("auditor_id")
    audit_type = body.get("audit_type")
    announcement = body.get("announcement")
    scheduled_start = body.get("scheduled_start")
    scheduled_end = body.get("scheduled_end")
    if not isinstance(facility_id, str) or not facility_id:
        raise_err(ERR_INVALID_REQUEST, "facility_id is required")
    if not isinstance(auditor_id, str) or not auditor_id:
        raise_err(ERR_INVALID_REQUEST, "auditor_id is required")
    if audit_type not in AUDIT_TYPES:
        raise_err(ERR_INVALID_REQUEST, f"audit_type must be one of {sorted(AUDIT_TYPES)}")
    if announcement not in ANNOUNCEMENTS:
        raise_err(ERR_INVALID_REQUEST, f"announcement must be one of {sorted(ANNOUNCEMENTS)}")
    if not isinstance(scheduled_start, str) or not scheduled_start:
        raise_err(ERR_INVALID_REQUEST, "scheduled_start is required")
    if not isinstance(scheduled_end, str) or not scheduled_end:
        raise_err(ERR_INVALID_REQUEST, "scheduled_end is required")

    # Existence (left-to-right): facility then auditor
    facility = db.facilities.get(facility_id)
    if not facility:
        raise_err(ERR_NOT_FOUND, "facility not found")
    auditor = db.auditors.get(auditor_id)
    if not auditor:
        raise_err(ERR_NOT_FOUND, "auditor not found")

    # State: supplier before facility before auditor
    supplier = db.suppliers.get(facility["supplier_id"])
    if not supplier or supplier["status"] not in ("ACTIVE", "PROBATION"):
        raise_err(ERR_SUPPLIER_NOT_AUDITABLE,
                  f"supplier status is {supplier['status'] if supplier else 'missing'}")
    if facility["status"] != "ACTIVE":
        raise_err(ERR_FACILITY_NOT_ACTIVE, f"facility status is {facility['status']}")
    if auditor["status"] != "ACTIVE":
        raise_err(ERR_AUDITOR_NOT_ACTIVE, f"auditor status is {auditor['status']}")

    # Country coverage (422)
    if facility["country_code"] not in auditor["country_codes_covered"]:
        raise_err(ERR_AUDITOR_COUNTRY_NOT_COVERED,
                  f"auditor does not cover country {facility['country_code']}")

    # One open audit per facility
    for a in db.audits.values():
        if a["facility_id"] == facility_id and a["status"] in ("SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED"):
            raise_err(ERR_AUDIT_ALREADY_OPEN, "an open audit exists at the facility")

    # ANNUAL blocked by valid accepted mutual recognition claim
    if audit_type == "ANNUAL":
        claim = _valid_accepted_claim_for_facility(facility_id)
        if claim is not None:
            raise_err(ERR_COVERED_BY_MUTUAL_RECOGNITION,
                      "facility covered by valid mutual recognition claim")

    # Temporal: window shape + start >= now
    start_dt = parse_iso(scheduled_start)
    end_dt = parse_iso(scheduled_end)
    now_dt = parse_iso(db.get_clock())
    if start_dt is None or end_dt is None:
        raise_err(ERR_INVALID_AUDIT_WINDOW, "scheduled_start/scheduled_end must be valid ISO-8601")
    if start_dt < now_dt:
        raise_err(ERR_INVALID_AUDIT_WINDOW, "scheduled_start must be >= current logical clock")
    span_seconds = (end_dt - start_dt).total_seconds()
    span_days = span_seconds / 86400.0
    if announcement == "ANNOUNCED":
        if span_days < 1 or span_days > 10:
            raise_err(ERR_INVALID_AUDIT_WINDOW, "ANNOUNCED span must be 1-10 days")
    else:  # SEMI_ANNOUNCED
        if span_days < 14 or span_days > 60:
            raise_err(ERR_INVALID_AUDIT_WINDOW, "SEMI_ANNOUNCED span must be 14-60 days")

    # Auditor double-booking: half-open [start, end) must not intersect any non-CANCELLED
    # audit of the same auditor. Conflict iff new.start < existing.end AND new.end > existing.start.
    for a in db.audits.values():
        if a["auditor_id"] != auditor_id or a["status"] == "CANCELLED":
            continue
        ex_start = parse_iso(a["scheduled_start"])
        ex_end = parse_iso(a["scheduled_end"])
        if ex_start is None or ex_end is None:
            continue
        if start_dt < ex_end and end_dt > ex_start:
            raise_err(ERR_AUDITOR_BOOKING_CONFLICT,
                      "auditor double-booked with existing audit")

    # Facility spacing: new start >= 30 days after every non-CANCELLED audit's end at this facility
    from datetime import timedelta
    for a in db.audits.values():
        if a["facility_id"] != facility_id or a["status"] == "CANCELLED":
            continue
        ex_end = parse_iso(a["scheduled_end"])
        if ex_end is None:
            continue
        min_start = ex_end + timedelta(days=30)
        if start_dt < min_start:
            raise_err(ERR_FACILITY_AUDIT_GAP_VIOLATION,
                      "new audit starts less than 30 days after previous audit at facility")

    audit = {
        "id": new_uuid(),
        "facility_id": facility_id,
        "auditor_id": auditor_id,
        "audit_type": audit_type,
        "announcement": announcement,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "zt_count": 0,
        "major_count": 0,
        "minor_count": 0,
        "cancel_reason": None,
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.audits[audit["id"]] = audit
    return success_object(serialize(audit), 201)


@bp.route("/audits", methods=["GET"])
def list_audits():
    require_roles(*ALL_BUSINESS_ROLES)
    limit, offset = get_pagination()
    fid = request.args.get("facility_id")
    aid = request.args.get("auditor_id")
    status_f = request.args.get("status")
    atype = request.args.get("audit_type")
    items = list(db.audits.values())
    if fid is not None:
        items = [a for a in items if a["facility_id"] == fid]
    if aid is not None:
        items = [a for a in items if a["auditor_id"] == aid]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if atype is not None:
        items = [a for a in items if a["audit_type"] == atype]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(a) for a in page], total, limit, offset)


@bp.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles(*ALL_BUSINESS_ROLES)
    a = db.audits.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "audit not found")
    return success_object(serialize(a))


@bp.route("/audits/<aid>/start", methods=["POST"])
def start_audit(aid):
    user_id, _ = require_roles("Auditor")
    a = db.audits.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if a["status"] != "SCHEDULED":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {a['status']}")
    if user_id != a["auditor_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller is not the audit's lead auditor")
    now_dt = parse_iso(db.get_clock())
    start_dt = parse_iso(a["scheduled_start"])
    if start_dt is None or now_dt is None or now_dt < start_dt:
        raise_err(ERR_AUDIT_WINDOW_NOT_OPEN, "logical clock has not reached scheduled_start")
    a["status"] = "IN_PROGRESS"
    a["version"] += 1
    a["updated_at"] = db.get_clock()
    return success_object(serialize(a))


@bp.route("/audits/<aid>/submit-report", methods=["POST"])
def submit_report(aid):
    user_id, _ = require_roles("Auditor")
    a = db.audits.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if a["status"] != "IN_PROGRESS":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {a['status']}")
    if user_id != a["auditor_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller is not the audit's lead auditor")
    # Require interview record
    record = next((r for r in db.worker_interview_records.values() if r["audit_id"] == aid), None)
    if record is None:
        raise_err(ERR_INTERVIEW_RECORD_MISSING, "worker interview record required")
    a["status"] = "REPORT_SUBMITTED"
    a["version"] += 1
    a["updated_at"] = db.get_clock()
    supplier, _fac = find_supplier_for_audit(a)
    if supplier is not None:
        recompute_supplier_scorecard(supplier)
    return success_object(serialize(a))


@bp.route("/audits/<aid>/decide", methods=["POST"])
def decide_audit(aid):
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if not isinstance(decision, str) or not decision:
        raise_err(ERR_INVALID_REQUEST, "decision is required")
    a = db.audits.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if a["status"] != "REPORT_SUBMITTED":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {a['status']}")
    if decision == "COMPLETE":
        # Check unresolved critical grievances at the facility
        for g in db.grievances.values():
            if (g["facility_id"] == a["facility_id"]
                    and g["severity"] == "CRITICAL"
                    and g["status"] in ("SUBMITTED", "UNDER_REVIEW", "ESCALATED")):
                raise_err(ERR_CRITICAL_GRIEVANCE_UNRESOLVED,
                          "unresolved CRITICAL grievance at facility")
        a["status"] = "COMPLETED"
        a["version"] += 1
        a["updated_at"] = db.get_clock()
        # Side effects: facility risk recompute + supplier scorecard
        facility = db.facilities.get(a["facility_id"])
        if facility is not None:
            recompute_facility_risk(facility)
        supplier, _ = find_supplier_for_audit(a)
        if supplier is not None:
            recompute_supplier_scorecard(supplier)
    elif decision == "RETURN_FOR_CORRECTION":
        a["status"] = "IN_PROGRESS"
        a["version"] += 1
        a["updated_at"] = db.get_clock()
    else:
        raise_err(ERR_INVALID_REQUEST, f"invalid decision {decision}")
    return success_object(serialize(a))


@bp.route("/audits/<aid>/cancel", methods=["POST"])
def cancel_audit(aid):
    require_roles("AuditCoordinator")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    a = db.audits.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if a["status"] != "SCHEDULED":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {a['status']}")
    a["status"] = "CANCELLED"
    if reason is not None:
        a["cancel_reason"] = reason
    a["version"] += 1
    a["updated_at"] = db.get_clock()
    return success_object(serialize(a))
