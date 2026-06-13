"""Cohort lifecycle + clock control (PRD §3.1, §2.10)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch
from middleware import require_role
from response import success
from services import serialize
from services.common import (
    get_json_body, parse_pagination, sort_by_created, paginate, lookup,
    require_fields, as_int, as_enum, as_str,
)
from services.timeutil import parse_dt

bp = Blueprint("cohorts", __name__)

TRACKS = {"FULLSTACK", "DATA", "CYBER"}
COHORT_STATUSES = {"PLANNING", "OPEN", "RUNNING", "GRADUATED", "ARCHIVED"}


@bp.post("/cohorts")
def create_cohort():
    require_role("AdmissionsOfficer")
    body = get_json_body()
    require_fields(body, ["name", "track", "capacity", "tuition_sticker_cents",
                          "start_date", "end_date", "cirr_period_label"])
    name = as_str(body, "name")
    track = as_enum(body, "track", TRACKS)
    capacity = as_int(body, "capacity", min_value=1)
    tuition = as_int(body, "tuition_sticker_cents", min_value=0)
    cirr_label = as_str(body, "cirr_period_label")
    start_dt = parse_dt(body["start_date"], "start_date")
    end_dt = parse_dt(body["end_date"], "end_date")
    if not (end_dt > start_dt):
        raise errors.invalid_request("end_date must be after start_date")

    c = {
        "name": name,
        "track": track,
        "capacity": capacity,
        "tuition_sticker_cents": tuition,
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "cirr_period_label": cirr_label,
        "status": "PLANNING",
    }
    stamp_create(c)
    db.cohorts[c["id"]] = c
    return success(serialize.cohort_view(c), status=201)


@bp.get("/cohorts/<cid>")
def get_cohort(cid):
    require_role("AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer", "Student")
    c = lookup(db.cohorts, cid)
    return success(serialize.cohort_view(c))


@bp.get("/cohorts")
def list_cohorts():
    require_role("AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer", "Student")
    limit, offset = parse_pagination()
    from flask import request
    status = request.args.get("status")
    rows = list(db.cohorts.values())
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.cohort_view(c) for c in window], pagination=pg)


def _transition_cohort(cid, frm, to, timing_check=None):
    require_role("AdmissionsOfficer")
    c = lookup(db.cohorts, cid)
    if c["status"] != frm:
        raise errors.invalid_state(f"Cohort is {c['status']}, expected {frm}")
    if timing_check is not None:
        timing_check(c)
    return c


@bp.post("/cohorts/<cid>/open")
def open_cohort(cid):
    def timing(c):
        if not (c["_start_dt"] > db.current_clock):
            raise errors.ApiError(errors.ERR_COHORT_TIMING, 409,
                                  "Cohort start_date must be in the future to open")
    c = _transition_cohort(cid, "PLANNING", "OPEN", timing)
    c["status"] = "OPEN"
    touch(c)
    return success(serialize.cohort_view(c))


@bp.post("/cohorts/<cid>/start")
def start_cohort(cid):
    def timing(c):
        if not (db.current_clock >= c["_start_dt"]):
            raise errors.ApiError(errors.ERR_COHORT_TIMING, 409,
                                  "Current clock has not reached start_date")
    c = _transition_cohort(cid, "OPEN", "RUNNING", timing)
    c["status"] = "RUNNING"
    touch(c)
    # cascade: every ENROLLED enrollment for this cohort -> ACTIVE
    for e in db.enrollments.values():
        if e["cohort_id"] == cid and e["status"] == "ENROLLED":
            e["status"] = "ACTIVE"
            touch(e)
    return success(serialize.cohort_view(c))


@bp.post("/cohorts/<cid>/graduate")
def graduate_cohort(cid):
    def timing(c):
        if not (db.current_clock >= c["_end_dt"]):
            raise errors.ApiError(errors.ERR_COHORT_TIMING, 409,
                                  "Current clock has not reached end_date")
    c = _transition_cohort(cid, "RUNNING", "GRADUATED", timing)
    c["status"] = "GRADUATED"
    touch(c)
    from services.derive import enrollment_attendance
    # cascade: each ACTIVE enrollment with progress_pct >= 100 -> GRADUATED;
    # each graduating ISA enrollment activates its PENDING ISAContract -> ACTIVE
    for e in db.enrollments.values():
        if e["cohort_id"] == cid and e["status"] == "ACTIVE":
            _, progress = enrollment_attendance(e["id"])
            if progress >= 100:
                e["status"] = "GRADUATED"
                touch(e)
                _activate_isa_for_enrollment(e["id"])
    return success(serialize.cohort_view(c))


def _activate_isa_for_enrollment(enrollment_id):
    contract = next(
        (c for c in db.isa_contracts.values() if c["enrollment_id"] == enrollment_id),
        None,
    )
    if contract is not None and contract["status"] == "PENDING":
        contract["status"] = "ACTIVE"
        from services.derive import recompute_isa_ledger
        recompute_isa_ledger(contract)  # remaining_cap_cents = cap_cents
        touch(contract)


@bp.post("/cohorts/<cid>/archive")
def archive_cohort(cid):
    c = _transition_cohort(cid, "GRADUATED", "ARCHIVED")
    # precondition: no ISAContract for this cohort in PENDING
    for contract in db.isa_contracts.values():
        enr = db.enrollments.get(contract["enrollment_id"])
        if enr and enr["cohort_id"] == cid and contract["status"] == "PENDING":
            raise errors.invalid_state("Cohort has a PENDING ISA contract; cannot archive")
    c["status"] = "ARCHIVED"
    touch(c)
    return success(serialize.cohort_view(c))


@bp.get("/cohorts/<cid>/enrollments")
def list_cohort_enrollments(cid):
    require_role("AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer")
    limit, offset = parse_pagination()
    lookup(db.cohorts, cid)
    rows = [e for e in db.enrollments.values() if e["cohort_id"] == cid]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.enrollment_view(e) for e in window], pagination=pg)


@bp.get("/cohorts/<cid>/cirr-reports")
def list_cohort_cirr_reports(cid):
    require_role("ComplianceOfficer")
    limit, offset = parse_pagination()
    lookup(db.cohorts, cid)
    rows = [r for r in db.cirr_reports.values() if r["cohort_id"] == cid]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.cirr_report_view(r) for r in window], pagination=pg)


# --- server clock (PRD §2.10) --------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role("AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer")
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    db.current_clock = parse_dt(body["to_iso8601"], "to_iso8601")
    return success({})
