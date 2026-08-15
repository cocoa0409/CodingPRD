"""Absence endpoints: report, get, list, OCC edit, cancel, review, claim."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_ABSENCE_NOT_FOUND, ERR_STAFF_MEMBER_NOT_FOUND,
    ERR_SUBSTITUTE_NOT_FOUND, ERR_ABSENCE_INVALID_STATE,
    ERR_SUBSTITUTE_INVALID_STATE, ERR_SUBSTITUTE_DO_NOT_RETURN,
    ERR_CLEARANCE_INVALID, ERR_QUALIFICATION_MISMATCH,
    ERR_INVALID_DATE_RANGE, ERR_ABSENCE_DATE_OVERLAP,
    ERR_ASSIGNMENT_DATE_OVERLAP, ERR_COVERAGE_BUDGET_INSUFFICIENT,
    ERR_ASSIGNMENT_INVALID_STATE, ERR_STALE_VERSION,
)
from middleware import (
    auth_context, require_role, require_coordinator_school,
    require_teacher_self, ALL_ROLES,
)
from response import ok, paginated
from util import parse_date, weekday_count, ranges_overlap
from validate import body, req_str, req_enum, opt_str, opt_enum, req_date, opt_date, req_int

bp = Blueprint("absences", __name__)

ABSENCE_TYPES = ("SICK", "PERSONAL", "PROFESSIONAL_DEVELOPMENT", "JURY_DUTY")
GRADE_BANDS = ("ELEMENTARY", "MIDDLE", "HIGH")
FILL_STATUSES = ("REPORTED", "DISPATCHING", "ASSIGNED", "COMPLETED",
                 "UNFILLED", "COVERED_INTERNALLY", "CLOSED", "CANCELLED")


def _check_date_range(start_raw, end_raw, must_not_be_past):
    start = parse_date(start_raw)
    end = parse_date(end_raw)
    if end < start:
        raise_err(ERR_INVALID_DATE_RANGE, "end_date must not precede start_date")
    if must_not_be_past and start < domain.now().date():
        raise_err(ERR_INVALID_DATE_RANGE, "start_date must not be before the current date")
    if weekday_count(start, end) < 1:
        raise_err(ERR_INVALID_DATE_RANGE, "the range must contain at least one weekday")
    return start, end


def _check_staff_overlap(staff_member_id, start, end, exclude_absence_id=None):
    for a in STORE.absences.values():
        if a["staff_member_id"] != staff_member_id:
            continue
        if exclude_absence_id and a["id"] == exclude_absence_id:
            continue
        if a["fill_status"] == "CANCELLED":
            continue
        if ranges_overlap(parse_date(a["start_date"]), parse_date(a["end_date"]), start, end):
            raise_err(ERR_ABSENCE_DATE_OVERLAP,
                      "staff member already has a non-cancelled absence overlapping this range")


def _approval_for(total_days, district):
    return "PENDING" if total_days > district["long_term_approval_days"] else "NOT_REQUIRED"


@bp.route("/absences", methods=["POST"])
def create_absence():
    user_id, role = auth_context()
    data = body()
    staff_member_id = req_str(data, "staff_member_id")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    absence_type = req_enum(data, "absence_type", ABSENCE_TYPES)
    required_subject = req_str(data, "required_subject")
    required_grade_band = req_enum(data, "required_grade_band", GRADE_BANDS)
    require_role(role, ["Teacher", "SchoolCoordinator", "DistrictAdmin"])
    if role == "Teacher":
        require_teacher_self(user_id, staff_member_id)
    staff = STORE.staff_members.get(staff_member_id)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, staff["school_id"] if staff else None)
    if staff is None:
        raise_err(ERR_STAFF_MEMBER_NOT_FOUND, "staff member id does not exist")
    start, end = _check_date_range(start_date, end_date, must_not_be_past=True)
    _check_staff_overlap(staff_member_id, start, end)
    school = STORE.schools[staff["school_id"]]
    district = STORE.districts[school["district_id"]]
    total_days = weekday_count(start, end)
    a = new_entity(STORE.absences, {
        "staff_member_id": staff_member_id,
        "school_id": staff["school_id"],
        "start_date": start_date,
        "end_date": end_date,
        "absence_type": absence_type,
        "required_subject": required_subject,
        "required_grade_band": required_grade_band,
        "total_days": total_days,
        "fill_status": "REPORTED",
        "approval_status": _approval_for(total_days, district),
        "days_covered_internal": 0,
        "days_covered_sub": 0,
        "days_uncovered": total_days,
    })
    return ok(public(a), status=201)


@bp.route("/absences/<aid>", methods=["GET"])
def get_absence(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    a = STORE.absences.get(aid)
    if a is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    return ok(public(a))


@bp.route("/absences", methods=["GET"])
def list_absences():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    school_id = request.args.get("school_id")
    staff_member_id = request.args.get("staff_member_id")
    fill_status = request.args.get("fill_status")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    if from_date is not None and parse_date(from_date) is None:
        raise_err(ERR_INVALID_DATE_RANGE, "from_date must be an ISO date")
    if to_date is not None and parse_date(to_date) is None:
        raise_err(ERR_INVALID_DATE_RANGE, "to_date must be an ISO date")
    items = sorted(STORE.absences.values(), key=lambda a: (a["created_at"], a["_seq"]))
    if school_id is not None:
        items = [a for a in items if a["school_id"] == school_id]
    if staff_member_id is not None:
        items = [a for a in items if a["staff_member_id"] == staff_member_id]
    if fill_status is not None:
        items = [a for a in items if a["fill_status"] == fill_status]
    if from_date is not None:
        items = [a for a in items if parse_date(a["start_date"]) >= parse_date(from_date)]
    if to_date is not None:
        items = [a for a in items if parse_date(a["start_date"]) <= parse_date(to_date)]
    page, meta = paginated(items)
    return ok([public(a) for a in page], pagination=meta)


@bp.route("/absences/<aid>", methods=["PUT"])
def edit_absence(aid):
    user_id, role = auth_context()
    data = body()
    expected = req_int(data, "expected_absence_version")
    new_start = opt_date(data, "start_date")
    new_end = opt_date(data, "end_date")
    new_subject = opt_str(data, "required_subject")
    new_band = opt_enum(data, "required_grade_band", GRADE_BANDS)
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    a = STORE.absences.get(aid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, a["school_id"] if a else None)
    if a is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    if expected != a["version"]:
        raise_err(ERR_STALE_VERSION, "expected_absence_version does not match the current version")
    if a["fill_status"] not in ("REPORTED", "DISPATCHING", "UNFILLED", "COVERED_INTERNALLY"):
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "only an unassigned absence may be edited")
    start_raw = new_start if new_start is not None else a["start_date"]
    end_raw = new_end if new_end is not None else a["end_date"]
    start, end = _check_date_range(start_raw, end_raw, must_not_be_past=False)
    _check_staff_overlap(a["staff_member_id"], start, end, exclude_absence_id=aid)
    district = domain.absence_district(a)
    a["start_date"] = start_raw
    a["end_date"] = end_raw
    if new_subject is not None:
        a["required_subject"] = new_subject
    if new_band is not None:
        a["required_grade_band"] = new_band
    a["total_days"] = weekday_count(start, end)
    # Approval recomputation cuts both ways (PRD 3.3).
    if a["total_days"] > district["long_term_approval_days"]:
        if a["approval_status"] in ("APPROVED", "NOT_REQUIRED", "REJECTED"):
            a["approval_status"] = "PENDING"
    else:
        if a["approval_status"] == "PENDING":
            a["approval_status"] = "NOT_REQUIRED"
    domain.recompute_day_counters(a, touch_absence=False)
    touch(a)
    return ok(public(a))


@bp.route("/absences/<aid>/cancel", methods=["POST"])
def cancel_absence(aid):
    user_id, role = auth_context()
    body()  # tolerate an empty body
    require_role(role, ["Teacher", "SchoolCoordinator", "DistrictAdmin"])
    a = STORE.absences.get(aid)
    if role == "Teacher" and a is not None:
        require_teacher_self(user_id, a["staff_member_id"])
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, a["school_id"] if a else None)
    if a is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    if a["fill_status"] not in ("REPORTED", "DISPATCHING", "UNFILLED", "COVERED_INTERNALLY"):
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "an ASSIGNED or further-along absence cannot be cancelled")
    for asg in sorted(STORE.assignments.values(), key=lambda x: x["_seq"]):
        if asg["absence_id"] == aid and asg["status"] == "OFFERED":
            domain.cancel_assignment(asg, "ABSENCE_CANCEL")
    for cov in sorted(STORE.coverages.values(), key=lambda x: x["_seq"]):
        if cov["absence_id"] == aid and cov["status"] in ("PROPOSED", "APPROVED"):
            cov["status"] = "CANCELLED"
            touch(cov)
    domain.recompute_day_counters(a, touch_absence=False)
    a["fill_status"] = "CANCELLED"
    touch(a)
    return ok(public(a))


@bp.route("/absences/<aid>/review", methods=["POST"])
def review_absence(aid):
    _, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    require_role(role, ["DistrictAdmin"])
    a = STORE.absences.get(aid)
    if a is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    if decision == "APPROVE":
        if a["approval_status"] not in ("PENDING", "NOT_REQUIRED"):
            raise_err(ERR_ABSENCE_INVALID_STATE,
                      "approval is permitted only from PENDING or NOT_REQUIRED")
        if a["fill_status"] in ("CANCELLED", "CLOSED"):
            raise_err(ERR_ABSENCE_INVALID_STATE,
                      "a cancelled or closed absence cannot be approved")
        a["approval_status"] = "APPROVED"
        touch(a)
    else:
        if a["approval_status"] not in ("PENDING", "NOT_REQUIRED"):
            raise_err(ERR_ABSENCE_INVALID_STATE,
                      "rejection is permitted only from PENDING or NOT_REQUIRED")
        if a["fill_status"] not in ("REPORTED", "DISPATCHING", "UNFILLED"):
            raise_err(ERR_ABSENCE_INVALID_STATE,
                      "rejection requires fill_status REPORTED, DISPATCHING, or UNFILLED")
        for asg in sorted(STORE.assignments.values(), key=lambda x: x["_seq"]):
            if asg["absence_id"] == aid and asg["status"] == "OFFERED":
                domain.cancel_assignment(asg, "ABSENCE_CANCEL")
        if a["fill_status"] in ("DISPATCHING", "UNFILLED"):
            a["fill_status"] = "REPORTED"
        a["approval_status"] = "REJECTED"
        touch(a)
    return ok(public(a))


@bp.route("/absences/<aid>/claim", methods=["POST"])
def claim_absence(aid):
    user_id, role = auth_context()
    data = body()
    expected = req_int(data, "expected_absence_version")
    require_role(role, ["Substitute"])
    a = STORE.absences.get(aid)
    if a is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    if expected != a["version"]:
        raise_err(ERR_STALE_VERSION, "expected_absence_version does not match the current version")
    if a["fill_status"] != "DISPATCHING":
        raise_err(ERR_ABSENCE_INVALID_STATE, "only a DISPATCHING absence may be claimed")
    if a["approval_status"] in ("PENDING", "REJECTED"):
        raise_err(ERR_ABSENCE_INVALID_STATE, "absence approval does not allow claiming")
    sub = STORE.substitutes.get(user_id)
    if sub is None:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    domain.refresh_substitute_scores(sub)
    if sub["status"] != "ACTIVE":
        raise_err(ERR_SUBSTITUTE_INVALID_STATE, "only an ACTIVE substitute may claim")
    if domain.active_mark(a["school_id"], sub["id"], "DO_NOT_RETURN"):
        raise_err(ERR_SUBSTITUTE_DO_NOT_RETURN,
                  "an ACTIVE DO_NOT_RETURN mark exists for this school and substitute")
    if not domain.required_clearances_valid(sub["id"], parse_date(a["end_date"])):
        raise_err(ERR_CLEARANCE_INVALID,
                  "required clearances must be VERIFIED through the absence end_date")
    if not domain.has_qualification(sub["id"], a["required_subject"], a["required_grade_band"]):
        raise_err(ERR_QUALIFICATION_MISMATCH, "substitute lacks the required qualification")
    if domain.has_assignment_overlap(sub["id"], parse_date(a["start_date"]), parse_date(a["end_date"])):
        raise_err(ERR_ASSIGNMENT_DATE_OVERLAP,
                  "substitute already holds a committed assignment overlapping this range")
    if (domain.existing_assignment_for(aid, sub["id"], ("OFFERED", "ACCEPTED"))
            or domain.existing_assignment_for(aid, sub["id"], ("DECLINED", "EXPIRED"))):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "a substitute who was already offered or declined may not claim")
    school = STORE.schools[a["school_id"]]
    district = domain.absence_district(a)
    asg = domain.create_offer(a, sub, "SELF_CLAIM")
    if domain.budget_available(school) < asg["provisional_pay_cents"]:
        # Roll the uncommitted offer back: acceptance is atomic.
        del STORE.assignments[asg["id"]]
        raise_err(ERR_COVERAGE_BUDGET_INSUFFICIENT,
                  "school coverage budget cannot cover the provisional pay")
    asg["status"] = "ACCEPTED"
    touch(asg)
    for other in sorted(STORE.assignments.values(), key=lambda x: x["_seq"]):
        if other["absence_id"] == aid and other["id"] != asg["id"] and other["status"] == "OFFERED":
            domain.cancel_assignment(other, "ABSENCE_CANCEL")
    school["coverage_budget_committed_cents"] += asg["provisional_pay_cents"]
    touch(school)
    a["fill_status"] = "ASSIGNED"
    touch(a)
    return ok(public(asg), status=201)
