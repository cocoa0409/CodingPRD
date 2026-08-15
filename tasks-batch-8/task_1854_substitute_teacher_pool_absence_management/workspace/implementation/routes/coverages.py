"""InternalCoverage endpoints: propose, get, list per absence/staff,
review, confirm-worked, cancel."""

from flask import Blueprint

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_ABSENCE_NOT_FOUND, ERR_STAFF_MEMBER_NOT_FOUND,
    ERR_COVERAGE_NOT_FOUND, ERR_ABSENCE_INVALID_STATE,
    ERR_COVERAGE_INVALID_STATE, ERR_INVALID_DATE_RANGE,
    ERR_COVERAGE_CAPACITY_EXCEEDED,
)
from middleware import auth_context, require_role, require_coordinator_school, ALL_ROLES
from response import ok, paginated
from util import parse_date, is_weekday
from validate import body, req_str, req_enum, req_date, req_periods

bp = Blueprint("coverages", __name__)


def _get_coverage_or_404(cid):
    c = STORE.coverages.get(cid)
    if c is None:
        raise_err(ERR_COVERAGE_NOT_FOUND, "internal coverage id does not exist")
    return c


def _recompute_and_transition(absence):
    """Recompute internal day counters; first approved coverage moves
    UNFILLED -> COVERED_INTERNALLY, and emptying the count moves it back."""
    was = absence["fill_status"]
    domain.recompute_day_counters(absence, touch_absence=False)
    if absence["days_covered_internal"] > 0 and was == "UNFILLED":
        absence["fill_status"] = "COVERED_INTERNALLY"
    elif absence["days_covered_internal"] == 0 and was == "COVERED_INTERNALLY":
        absence["fill_status"] = "UNFILLED"
    touch(absence)


@bp.route("/internal-coverages", methods=["POST"])
def create_coverage():
    user_id, role = auth_context()
    data = body()
    absence_id = req_str(data, "absence_id")
    staff_member_id = req_str(data, "staff_member_id")
    coverage_date = req_date(data, "coverage_date")
    periods = req_periods(data, "periods")
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    absence = STORE.absences.get(absence_id)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, absence["school_id"] if absence else None)
    if absence is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    if staff_member_id not in STORE.staff_members:
        raise_err(ERR_STAFF_MEMBER_NOT_FOUND, "staff member id does not exist")
    if absence["fill_status"] not in ("DISPATCHING", "UNFILLED", "COVERED_INTERNALLY"):
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "coverage requires fill_status DISPATCHING, UNFILLED, or COVERED_INTERNALLY")
    d = parse_date(coverage_date)
    if (not is_weekday(d) or d < parse_date(absence["start_date"])
            or d > parse_date(absence["end_date"])):
        raise_err(ERR_INVALID_DATE_RANGE,
                  "coverage_date must be a weekday inside the absence range")
    district = domain.absence_district(absence)
    if not domain.coverage_capacity_ok(staff_member_id, d, periods, district):
        raise_err(ERR_COVERAGE_CAPACITY_EXCEEDED,
                  "coverage would exceed the daily or weekly period cap")
    c = new_entity(STORE.coverages, {
        "absence_id": absence_id,
        "staff_member_id": staff_member_id,
        "school_id": absence["school_id"],
        "coverage_date": coverage_date,
        "periods": periods,
        "status": "PROPOSED",
        "compensation_cents": None,
    })
    return ok(public(c), status=201)


@bp.route("/internal-coverages/<cid>", methods=["GET"])
def get_coverage(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(_get_coverage_or_404(cid)))


@bp.route("/absences/<aid>/internal-coverages", methods=["GET"])
def list_absence_coverages(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if aid not in STORE.absences:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    items = sorted((c for c in STORE.coverages.values() if c["absence_id"] == aid),
                   key=lambda c: (c["created_at"], c["_seq"]))
    page, meta = paginated(items)
    return ok([public(c) for c in page], pagination=meta)


@bp.route("/staff-members/<mid>/internal-coverages", methods=["GET"])
def list_staff_coverages(mid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if mid not in STORE.staff_members:
        raise_err(ERR_STAFF_MEMBER_NOT_FOUND, "staff member id does not exist")
    items = sorted((c for c in STORE.coverages.values() if c["staff_member_id"] == mid),
                   key=lambda c: (c["created_at"], c["_seq"]))
    page, meta = paginated(items)
    return ok([public(c) for c in page], pagination=meta)


@bp.route("/internal-coverages/<cid>/review", methods=["POST"])
def review_coverage(cid):
    _, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    require_role(role, ["DistrictAdmin"])
    c = _get_coverage_or_404(cid)
    if c["status"] != "PROPOSED":
        raise_err(ERR_COVERAGE_INVALID_STATE, "review requires status PROPOSED")
    absence = STORE.absences[c["absence_id"]]
    if decision == "REJECT":
        c["status"] = "REJECTED"
        touch(c)
        return ok(public(c))
    if absence["fill_status"] not in ("UNFILLED", "COVERED_INTERNALLY"):
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "coverage approval requires fill_status UNFILLED or COVERED_INTERNALLY")
    district = domain.absence_district(absence)
    if not domain.coverage_capacity_ok(c["staff_member_id"], parse_date(c["coverage_date"]),
                                       0, district):
        raise_err(ERR_COVERAGE_CAPACITY_EXCEEDED,
                  "coverage would exceed the daily or weekly period cap")
    c["status"] = "APPROVED"
    touch(c)
    _recompute_and_transition(absence)
    return ok(public(c))


@bp.route("/internal-coverages/<cid>/confirm-worked", methods=["POST"])
def confirm_worked(cid):
    user_id, role = auth_context()
    body()
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    c = STORE.coverages.get(cid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, c["school_id"] if c else None)
    if c is None:
        raise_err(ERR_COVERAGE_NOT_FOUND, "internal coverage id does not exist")
    if c["status"] != "APPROVED":
        raise_err(ERR_COVERAGE_INVALID_STATE, "confirm-worked requires status APPROVED")
    if domain.now().date() < parse_date(c["coverage_date"]):
        raise_err(ERR_COVERAGE_INVALID_STATE, "the coverage_date has not been reached")
    district = domain.absence_district(STORE.absences[c["absence_id"]])
    # The rate is read and snapshotted at confirmation time.
    c["compensation_cents"] = c["periods"] * district["period_comp_rate_cents"]
    c["status"] = "WORKED"
    touch(c)
    return ok(public(c))


@bp.route("/internal-coverages/<cid>/cancel", methods=["POST"])
def cancel_coverage(cid):
    user_id, role = auth_context()
    body()
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    c = STORE.coverages.get(cid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, c["school_id"] if c else None)
    if c is None:
        raise_err(ERR_COVERAGE_NOT_FOUND, "internal coverage id does not exist")
    if c["status"] not in ("PROPOSED", "APPROVED"):
        raise_err(ERR_COVERAGE_INVALID_STATE,
                  "only a PROPOSED or APPROVED coverage may be cancelled")
    was_approved = c["status"] == "APPROVED"
    c["status"] = "CANCELLED"
    touch(c)
    if was_approved:
        _recompute_and_transition(STORE.absences[c["absence_id"]])
    return ok(public(c))
