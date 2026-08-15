"""Routes: anesthesia cases (schedule/reschedule/start/complete/cancel) + case assignments."""
from flask import Blueprint, request

from store import db
from errors import ApiError, err_invalid_time_window
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters
import calc
import services
import serializers as ser

bp = Blueprint("cases", __name__, url_prefix="/anesthesia-ops")

SCHED = ["Scheduler"]
ALL = ["GroupAdministrator", "Scheduler", "AttendingAnesthesiologist", "CRNA",
       "BillingSpecialist", "ComplianceAuditor"]
ENTITY_BACKED = ["AttendingAnesthesiologist", "CRNA"]

PS_VALUES = ("P1", "P2", "P3", "P4", "P5", "P6")


def _get_case(case_id):
    rec = db.cases.get(case_id)
    if rec is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case not found")
    return rec


def _check_window(start, end):
    if not (0 <= start < end <= 1439):
        raise err_invalid_time_window()


# ----------------------------------------------------------- safety gates ----
def _check_credential_currency(provider, service_date):
    if service_date > provider["credential_expires_on"] or \
            service_date > provider["dea_expires_on"]:
        raise ApiError("ERR_CREDENTIAL_EXPIRED", 409,
                       "Provider credentials are not current for the service date")


def _check_supervision_ratio(provider_id, service_date, start, end, candidate_case_id):
    """7b: peak directed concurrency (half-open) incl. candidate must stay <= RATIO_MAX."""
    intervals = []
    for a, c in calc.directing_intervals_for(provider_id, service_date):
        if c["id"] == candidate_case_id:
            continue
        intervals.append((c["scheduled_start_minute"], c["scheduled_end_minute"]))
    intervals.append((start, end))
    if calc.peak_overlap(intervals) > calc.RATIO_MAX:
        raise ApiError("ERR_SUPERVISION_RATIO_EXCEEDED", 409,
                       "Directing peak concurrency would exceed 4 rooms")


def _check_directing_vs_own_primary(provider_id, service_date, start, end):
    """A physician may not direct a case overlapping one they personally perform."""
    for a, c in calc.primary_intervals_for(provider_id, service_date):
        if calc.half_open_overlap(start, end, c["scheduled_start_minute"],
                                  c["scheduled_end_minute"]):
            raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409,
                           "Physician cannot direct while personally performing")


def _check_primary_double_book(provider, service_date, start, end, candidate_case_id):
    """Half-open pairwise check vs the provider's primaries (and, for MDs, directing)."""
    pid = provider["id"]
    is_md = provider["provider_type"] == "ANESTHESIOLOGIST"
    for a in db.assignments.values():
        if a["provider_id"] != pid or a["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        c = db.cases.get(a["case_id"])
        if c is None or calc.service_date_of_case(c) != service_date:
            continue
        if a["assignment_role"] == "CASE_PRIMARY":
            if c["id"] == candidate_case_id:
                continue  # same-role live assignment on this case is being superseded
        elif not (is_md and a["assignment_role"] == "CASE_DIRECTING"):
            continue
        if calc.half_open_overlap(start, end, c["scheduled_start_minute"],
                                  c["scheduled_end_minute"]):
            raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409,
                           "Provider already has a conflicting case assignment")


def _check_rest(provider_id, service_date, start):
    for ca in db.call_assignments.values():
        if ca["provider_id"] != provider_id:
            continue
        r = db.rosters.get(ca["roster_id"])
        if r is None or r["service_date"] != service_date:
            continue
        if ca["window_end_minute"] <= start and \
                start - ca["window_end_minute"] < calc.REST_MINUTES:
            raise ApiError("ERR_INSUFFICIENT_REST", 409,
                           "Case start is less than 480 minutes after call window end")


def _revalidate_after_reschedule(case, new_start, new_end):
    roster = db.rosters[case["roster_id"]]
    sd = roster["service_date"]
    live = [a for a in db.assignments.values()
            if a["case_id"] == case["id"] and a["status"] in ("PROPOSED", "CONFIRMED")]
    # 7b supervision ratio for directing assignments (with the case's new interval)
    for a in live:
        if a["assignment_role"] != "CASE_DIRECTING":
            continue
        intervals = []
        for b, cb in calc.directing_intervals_for(a["provider_id"], sd):
            if cb["id"] == case["id"]:
                intervals.append((new_start, new_end))
            else:
                intervals.append((cb["scheduled_start_minute"], cb["scheduled_end_minute"]))
        if calc.peak_overlap(intervals) > calc.RATIO_MAX:
            raise ApiError("ERR_SUPERVISION_RATIO_EXCEEDED", 409,
                           "Directing peak concurrency would exceed 4 rooms")
    # 9 double-booking
    for a in live:
        if a["assignment_role"] == "CASE_DIRECTING":
            for b, cb in calc.primary_intervals_for(a["provider_id"], sd):
                bs, be = (new_start, new_end) if cb["id"] == case["id"] else \
                    (cb["scheduled_start_minute"], cb["scheduled_end_minute"])
                if calc.half_open_overlap(new_start, new_end, bs, be):
                    raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409,
                                   "Physician cannot direct while personally performing")
    for a in live:
        if a["assignment_role"] != "CASE_PRIMARY":
            continue
        provider = db.providers[a["provider_id"]]
        is_md = provider["provider_type"] == "ANESTHESIOLOGIST"
        for b in db.assignments.values():
            if b["id"] == a["id"] or b["provider_id"] != provider["id"] or \
                    b["status"] not in ("PROPOSED", "CONFIRMED"):
                continue
            cb = db.cases.get(b["case_id"])
            if cb is None or calc.service_date_of_case(cb) != sd:
                continue
            if b["assignment_role"] != "CASE_PRIMARY" and \
                    not (is_md and b["assignment_role"] == "CASE_DIRECTING"):
                continue
            bs, be = (new_start, new_end) if cb["id"] == case["id"] else \
                (cb["scheduled_start_minute"], cb["scheduled_end_minute"])
            if calc.half_open_overlap(new_start, new_end, bs, be):
                raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409,
                               "Provider already has a conflicting case assignment")
    # 10 rest buffer
    for a in live:
        if a["assignment_role"] == "CASE_PRIMARY":
            _check_rest(a["provider_id"], sd, new_start)


# ------------------------------------------------------------------ cases ----
@bp.post("/cases")
def create_case():
    auth(SCHED)
    body = get_body()
    check_body(body, {
        "roster_id": {"kind": "str", "req": True},
        "procedure_code": {"kind": "str", "req": True},
        "physical_status": {"kind": ("enum", PS_VALUES), "req": True},
        "emergency_flag": {"kind": "bool", "req": False},
        "scheduled_start_minute": {"kind": "int", "req": True},
        "scheduled_end_minute": {"kind": "int", "req": True},
    })
    _check_window(body["scheduled_start_minute"], body["scheduled_end_minute"])
    roster = db.rosters.get(body["roster_id"])
    if roster is None:
        raise ApiError("ERR_ROSTER_NOT_FOUND", 404, "Roster not found")
    if calc.fee_by_code(body["procedure_code"]) is None:
        raise ApiError("ERR_UNKNOWN_PROCEDURE_CODE", 404,
                       "procedure_code matches no fee-schedule row")
    if roster["lifecycle"] == "LOCKED":
        raise ApiError("ERR_ROSTER_LIFECYCLE_LOCKED", 409,
                       "Mutation not allowed on a LOCKED roster")
    rec = db.new_record(
        roster_id=body["roster_id"], procedure_code=body["procedure_code"],
        physical_status=body["physical_status"],
        emergency_flag=body.get("emergency_flag", False),
        scheduled_start_minute=body["scheduled_start_minute"],
        scheduled_end_minute=body["scheduled_end_minute"],
        actual_start_minute=None, actual_end_minute=None, status="SCHEDULED",
        cancellation_reason=None, cancellation_notice_minutes=None,
        provisional_charge_cents=None, final_charge_cents=None)
    db.cases[rec["id"]] = rec
    return ok(ser.case(rec), 201)


@bp.get("/cases")
def list_cases():
    auth(ALL)
    items = apply_filters(db.cases.values(), request.args, ["roster_id", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.case(r) for r in page], limit, offset, total)


@bp.get("/cases/<case_id>")
def get_case(case_id):
    auth(ALL)
    return ok(ser.case(_get_case(case_id)))


@bp.patch("/cases/<case_id>")
def reschedule_case(case_id):
    auth(SCHED)
    body = get_body()
    check_body(body, {
        "scheduled_start_minute": {"kind": "int", "req": False},
        "scheduled_end_minute": {"kind": "int", "req": False},
        "expected_case_version": {"kind": "int", "req": True},
    })
    if "scheduled_start_minute" in body and "scheduled_end_minute" in body:
        _check_window(body["scheduled_start_minute"], body["scheduled_end_minute"])
    rec = _get_case(case_id)
    new_start = body.get("scheduled_start_minute", rec["scheduled_start_minute"])
    new_end = body.get("scheduled_end_minute", rec["scheduled_end_minute"])
    _check_window(new_start, new_end)
    roster = db.rosters[rec["roster_id"]]
    if roster["lifecycle"] == "LOCKED":
        raise ApiError("ERR_ROSTER_LIFECYCLE_LOCKED", 409,
                       "Mutation not allowed on a LOCKED roster")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_CASE_NOT_SCHEDULED", 409, "Case is not SCHEDULED")
    if body["expected_case_version"] != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Case version is stale")
    _revalidate_after_reschedule(rec, new_start, new_end)
    rec["scheduled_start_minute"] = new_start
    rec["scheduled_end_minute"] = new_end
    db.bump(rec)
    services.recompute_provisional(rec)
    return ok(ser.case(rec))


@bp.post("/cases/<case_id>/start")
def start_case(case_id):
    auth(SCHED)
    get_body()
    rec = _get_case(case_id)
    roster = db.rosters[rec["roster_id"]]
    if roster["lifecycle"] != "PUBLISHED":
        raise ApiError("ERR_ROSTER_NOT_PUBLISHED", 409, "Roster is not PUBLISHED")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_CASE_NOT_SCHEDULED", 409, "Case is not SCHEDULED")
    if db.clock_date_str() != roster["service_date"]:
        raise ApiError("ERR_CLOCK_DATE_MISMATCH", 409,
                       "Clock date must equal the roster service date")
    rec["actual_start_minute"] = db.clock_minute()
    rec["status"] = "IN_PROGRESS"
    db.bump(rec)
    return ok(ser.case(rec))


@bp.post("/cases/<case_id>/complete")
def complete_case(case_id):
    auth(SCHED)
    get_body()
    rec = _get_case(case_id)
    roster = db.rosters[rec["roster_id"]]
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CASE_NOT_IN_PROGRESS", 409, "Case is not IN_PROGRESS")
    if db.clock_date_str() != roster["service_date"]:
        raise ApiError("ERR_CLOCK_DATE_MISMATCH", 409,
                       "Clock date must equal the roster service date")
    clock_min = db.clock_minute()
    if clock_min <= rec["actual_start_minute"]:
        raise ApiError("ERR_INVALID_ACTUAL_MINUTES", 409,
                       "Clock minute must be strictly after actual_start_minute")
    services.complete_case(rec, clock_min)
    return ok(ser.case(rec))


@bp.post("/cases/<case_id>/cancel")
def cancel_case(case_id):
    auth(SCHED)
    body = get_body()
    check_body(body, {"cancellation_reason": {"kind": "str", "req": True}})
    rec = _get_case(case_id)
    roster = db.rosters[rec["roster_id"]]
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_CASE_NOT_CANCELLABLE", 409, "Case is not SCHEDULED")
    if db.clock_date_str() > roster["service_date"]:
        raise ApiError("ERR_CLOCK_DATE_MISMATCH", 409,
                       "Cannot cancel after the roster service date")
    services.cancel_case(rec, body["cancellation_reason"],
                         db.clock_date_str(), db.clock_minute())
    return ok(ser.case(rec))


# ------------------------------------------------------------- assignments ----
@bp.post("/cases/<case_id>/assignments")
def create_assignment(case_id):
    auth(SCHED)
    body = get_body()
    check_body(body, {
        "provider_id": {"kind": "str", "req": True},
        "assignment_role": {"kind": ("enum", ("CASE_PRIMARY", "CASE_DIRECTING")), "req": True},
        "expected_case_version": {"kind": "int", "req": True},
    })
    case = _get_case(case_id)
    provider = db.providers.get(body["provider_id"])
    if provider is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    roster = db.rosters[case["roster_id"]]
    if roster["lifecycle"] == "LOCKED":
        raise ApiError("ERR_ROSTER_LIFECYCLE_LOCKED", 409,
                       "Mutation not allowed on a LOCKED roster")
    if roster["lifecycle"] != "PUBLISHED":
        raise ApiError("ERR_ROSTER_NOT_PUBLISHED", 409, "Roster is not PUBLISHED")
    if case["status"] != "SCHEDULED":
        raise ApiError("ERR_CASE_NOT_SCHEDULED", 409, "Case is not SCHEDULED")
    if body["expected_case_version"] != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Case version is stale")

    sd = roster["service_date"]
    start, end = case["scheduled_start_minute"], case["scheduled_end_minute"]
    _check_credential_currency(provider, sd)
    if body["assignment_role"] == "CASE_DIRECTING":
        _check_supervision_ratio(provider["id"], sd, start, end, case["id"])
        _check_directing_vs_own_primary(provider["id"], sd, start, end)
    else:
        _check_primary_double_book(provider, sd, start, end, case["id"])
        _check_rest(provider["id"], sd, start)

    # supersede the live same-role assignment on this case
    superseded_primary_confirmed = False
    for a in db.assignments.values():
        if a["case_id"] == case["id"] and a["assignment_role"] == body["assignment_role"] \
                and a["status"] in ("PROPOSED", "CONFIRMED"):
            if a["assignment_role"] == "CASE_PRIMARY" and a["status"] == "CONFIRMED":
                superseded_primary_confirmed = True
            a["status"] = "SUPERSEDED"
            db.bump(a)
    rec = db.new_record(case_id=case["id"], roster_id=case["roster_id"],
                        provider_id=body["provider_id"],
                        assignment_role=body["assignment_role"], status="PROPOSED")
    db.assignments[rec["id"]] = rec
    if superseded_primary_confirmed:
        case["provisional_charge_cents"] = None
    db.bump(case)  # assignment churn is a case mutation
    return ok(ser.assignment(rec), 201)


@bp.get("/assignments")
def list_assignments():
    auth(ALL)
    items = apply_filters(db.assignments.values(), request.args,
                          ["case_id", "provider_id", "roster_id", "status", "assignment_role"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.assignment(r) for r in page], limit, offset, total)


@bp.get("/assignments/<asg_id>")
def get_assignment(asg_id):
    auth(ALL)
    rec = db.assignments.get(asg_id)
    if rec is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    return ok(ser.assignment(rec))


def _get_assignment(asg_id):
    rec = db.assignments.get(asg_id)
    if rec is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    return rec


@bp.post("/assignments/<asg_id>/accept")
def accept_assignment(asg_id):
    uid, _ = auth(ENTITY_BACKED)
    get_body()
    rec = _get_assignment(asg_id)
    if uid != rec["provider_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "X-User-ID must equal the assignment provider_id")
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_ASSIGNMENT_NOT_PROPOSED", 409, "Assignment is not PROPOSED")
    provider = db.providers[rec["provider_id"]]
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_SUSPENDED", 409, "Provider is SUSPENDED")
    roster = db.rosters[rec["roster_id"]]
    _check_credential_currency(provider, roster["service_date"])
    rec["status"] = "CONFIRMED"
    db.bump(rec)
    if rec["assignment_role"] == "CASE_PRIMARY":
        services.recompute_provisional(db.cases[rec["case_id"]])
    return ok(ser.assignment(rec))


@bp.post("/assignments/<asg_id>/decline")
def decline_assignment(asg_id):
    uid, _ = auth(ENTITY_BACKED)
    get_body()
    rec = _get_assignment(asg_id)
    if uid != rec["provider_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "X-User-ID must equal the assignment provider_id")
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_ASSIGNMENT_NOT_PROPOSED", 409, "Assignment is not PROPOSED")
    rec["status"] = "DECLINED"
    db.bump(rec)
    return ok(ser.assignment(rec))


@bp.post("/assignments/<asg_id>/cancel")
def cancel_assignment(asg_id):
    auth(SCHED)
    get_body()
    rec = _get_assignment(asg_id)
    case = db.cases[rec["case_id"]]
    if rec["status"] not in ("PROPOSED", "CONFIRMED") or case["status"] != "SCHEDULED":
        raise ApiError("ERR_ASSIGNMENT_NOT_CANCELLABLE", 409,
                       "Assignment cancel requires PROPOSED/CONFIRMED and a SCHEDULED case")
    was_confirmed_primary = rec["status"] == "CONFIRMED" and \
        rec["assignment_role"] == "CASE_PRIMARY"
    rec["status"] = "CANCELLED"
    db.bump(rec)
    if was_confirmed_primary:
        case["provisional_charge_cents"] = None
    return ok(ser.assignment(rec))
