"""SupervisionAssignment endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_PROVIDER_TYPE_INVALID,
    ERR_NO_EFFECTIVE_AGREEMENT, ERR_SUPERVISION_WINDOW_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from util import dec, decimal_places, parse_date_strict
from validate import (
    get_body, req_date, req_number, require_path_resource, require_body_ref,
)

bp = Blueprint("supervision", __name__)

SUPERVISION_ROLES = ["CompAnalyst", "CompCommittee", "ComplianceOfficer"]
FTE_CAPACITY_CAP = dec(4.0)


def _overlaps(s1, e1, s2, e2):
    """Closed-interval overlap."""
    return s1 <= e2 and s2 <= e1


def _window_sum_ok(items, new_start, new_end, new_value, cap) -> bool:
    """Point-wise sum check: for every day, the sum of values of windows covering
    that day (including the new one) must stay <= cap. items: (start_ord, end_ord, value)."""
    s, e = new_start.toordinal(), new_end.toordinal()
    pts = {s, e + 1}
    for (a1, a2, _v) in items:
        pts.add(a1)
        pts.add(a2 + 1)
    pts = sorted(pts)
    for i in range(len(pts) - 1):
        d0, d1 = pts[i], pts[i + 1]
        seg_day = d0  # representative day of the elementary segment [d0, d1)
        if not (s <= seg_day <= e):
            # segment outside the new window: the new value does not add, but
            # existing sums were valid at creation, so only segments inside the
            # new window can newly overflow.
            continue
        total = dec(new_value)
        for (a1, a2, v) in items:
            if a1 <= seg_day <= a2:
                total += dec(v)
        if total > cap:
            return False
    return True


@bp.post("/supervision-assignments")
def create_assignment():
    authorized(["CompAnalyst"])
    body = get_body()
    # Priority 4: body FK existence
    sup_id = body.get("supervisor_physician_id")
    app_id = body.get("app_physician_id")
    sup = require_body_ref("physicians", sup_id, "supervisor_physician_id")
    app = require_body_ref("physicians", app_id, "app_physician_id")
    # Priority 14: payload shape
    if not isinstance(sup_id, str) or not sup_id:
        raise_error(ERR_VALIDATION, "missing or invalid field: supervisor_physician_id")
    if not isinstance(app_id, str) or not app_id:
        raise_error(ERR_VALIDATION, "missing or invalid field: app_physician_id")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    credit_pct = req_number(body, "credit_pct")
    if not (dec(credit_pct) > 0 and dec(credit_pct) <= 1):
        raise_error(ERR_VALIDATION, "credit_pct must be in (0, 1]")
    if decimal_places(credit_pct) > 4:
        raise_error(ERR_VALIDATION, "credit_pct may carry up to 4 decimal places")
    supervised_fte = req_number(body, "supervised_fte")
    if not (dec(supervised_fte) > 0 and dec(supervised_fte) <= 4):
        raise_error(ERR_VALIDATION, "supervised_fte must be in (0, 4.0]")
    # Priority 18: provider types
    if (sup_id == app_id or sup["provider_type"] != "PHYSICIAN"
            or app["provider_type"] != "APP"):
        raise_error(ERR_PROVIDER_TYPE_INVALID,
                    "supervisor must be PHYSICIAN, app must be APP, and the two must differ")
    # Priority 19: both parties hold EFFECTIVE agreements on the same plan
    sup_plans = {a["plan_id"] for a in db["physician_agreements"].values()
                 if a["physician_id"] == sup_id and a["status"] == "EFFECTIVE"}
    app_plans = {a["plan_id"] for a in db["physician_agreements"].values()
                 if a["physician_id"] == app_id and a["status"] == "EFFECTIVE"}
    if not (sup_plans & app_plans):
        raise_error(ERR_NO_EFFECTIVE_AGREEMENT,
                    "supervisor and APP must each hold an EFFECTIVE agreement on the same plan")
    # Priority 20: window rules
    s = parse_date_strict(start_date)
    e = parse_date_strict(end_date)
    if e < s:
        raise_error(ERR_SUPERVISION_WINDOW_INVALID, "end_date must not precede start_date")
    active = [a for a in db["supervision_assignments"].values() if a["status"] == "ACTIVE"]
    # (a) same (supervisor, app) pair: closed windows must not overlap
    for a in active:
        if a["supervisor_physician_id"] == sup_id and a["app_physician_id"] == app_id:
            if _overlaps(s, e, parse_date_strict(a["start_date"]), parse_date_strict(a["end_date"])):
                raise_error(ERR_SUPERVISION_WINDOW_INVALID,
                            "overlapping windows for the same supervisor-APP pair")
    # (b) same APP across overlapping windows: credit_pct sums <= 1.0
    app_items = [
        (parse_date_strict(a["start_date"]).toordinal(),
         parse_date_strict(a["end_date"]).toordinal(), a["credit_pct"])
        for a in active if a["app_physician_id"] == app_id
    ]
    if not _window_sum_ok(app_items, s, e, credit_pct, dec(1)):
        raise_error(ERR_SUPERVISION_WINDOW_INVALID,
                    "credit_pct sums over overlapping windows for the same APP exceed 1.0")
    # (c) same supervisor: supervised_fte over any overlapping day <= 4.0
    sup_items = [
        (parse_date_strict(a["start_date"]).toordinal(),
         parse_date_strict(a["end_date"]).toordinal(), a["supervised_fte"])
        for a in active if a["supervisor_physician_id"] == sup_id
    ]
    if not _window_sum_ok(sup_items, s, e, supervised_fte, FTE_CAPACITY_CAP):
        raise_error(ERR_SUPERVISION_WINDOW_INVALID,
                    "supervisor supervised_fte commitments exceed 4.0 on an overlapping day")
    rec = new_record("supervision_assignments", {
        "supervisor_physician_id": sup_id,
        "app_physician_id": app_id,
        "start_date": start_date,
        "end_date": end_date,
        "credit_pct": credit_pct,
        "supervised_fte": supervised_fte,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/supervision-assignments")
def list_assignments():
    authorized(SUPERVISION_ROLES)
    filters = {
        "supervisor_physician_id": request.args.get("supervisor_physician_id"),
        "app_physician_id": request.args.get("app_physician_id"),
        "status": request.args.get("status"),
    }
    return list_response("supervision_assignments", filters)


@bp.get("/supervision-assignments/<rid>")
def get_assignment(rid):
    authorized(SUPERVISION_ROLES)
    rec = require_path_resource("supervision_assignments", rid)
    return success_object(public(rec))


@bp.post("/supervision-assignments/<rid>/end")
def end_assignment(rid):
    authorized(["CompAnalyst"])
    asg = require_path_resource("supervision_assignments", rid)
    if asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE assignment can be ended")
    body = get_body()
    end_date = req_date(body, "end_date")
    # Shrinking the window cannot create new overlaps; the end must not precede
    # the start (ERR_SUPERVISION_WINDOW_INVALID).
    if parse_date_strict(end_date) < parse_date_strict(asg["start_date"]):
        raise_error(ERR_SUPERVISION_WINDOW_INVALID, "end_date must not precede start_date")
    asg["end_date"] = end_date
    asg["status"] = "ENDED"
    touch("supervision_assignments", asg)
    return success_object(public(asg))
