"""Volunteer shift endpoints (PRD §3.7)."""

from datetime import timedelta

from db import store, base_fields, touch, now
from errors import (ERR_NOT_FOUND, ERR_VALIDATION, ERR_DUPLICATE_SIGNUP,
                    ERR_SHIFT_FULL, ERR_SHIFT_OVERLAP, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body
from serialize import shift_json
from validate import req_str, req_int, parse_datetime
from . import make_blueprint

bp = make_blueprint("shifts")

SIGNUP_ROLES = ["Volunteer", "VolunteerCoordinator"]
_BUFFER = timedelta(minutes=30)


def _get_shift_or_404(sid):
    s = store.volunteer_shifts.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Volunteer shift not found.")
    return s


@bp.route("/volunteer-shifts", methods=["POST"])
def create_shift():
    _, role = authenticate()
    require_role(role, ["VolunteerCoordinator"])
    body = get_body()
    title = req_str(body, "title")
    starts = parse_datetime(body.get("starts_at"), "starts_at")
    ends = parse_datetime(body.get("ends_at"), "ends_at")
    capacity = req_int(body, "capacity", minimum=1)
    if not (starts < ends):
        raise_err(ERR_VALIDATION, "starts_at must be before ends_at.")
    s = base_fields()
    s.update({
        "title": title,
        "starts_at": starts,
        "ends_at": ends,
        "capacity": capacity,
        "signups": [],
    })
    store.volunteer_shifts[s["id"]] = s
    return success_object(shift_json(s), status=201)


@bp.route("/volunteer-shifts/<sid>/signups", methods=["POST"])
def signup(sid):
    _, role = authenticate()
    require_role(role, SIGNUP_ROLES)
    s = _get_shift_or_404(sid)
    body = get_body()
    email = req_str(body, "volunteer_email")
    name = req_str(body, "volunteer_name")
    # Category 6 in the scaffold's declared order: overlap, then full, then
    # duplicate-on-this-shift.
    for other in store.volunteer_shifts.values():
        if other["id"] == s["id"]:
            continue
        if not any(x["volunteer_email"] == email for x in other["signups"]):
            continue
        # Other window expanded 30 minutes on both sides, half-open
        # intersection: an exactly-30-minute gap is allowed.
        if s["starts_at"] < other["ends_at"] + _BUFFER and \
                other["starts_at"] - _BUFFER < s["ends_at"]:
            raise_err(ERR_SHIFT_OVERLAP,
                      "Volunteer holds another shift within the 30-minute "
                      "buffer window.")
    if len(s["signups"]) >= s["capacity"]:
        raise_err(ERR_SHIFT_FULL, "Shift is at capacity.")
    if any(x["volunteer_email"] == email for x in s["signups"]):
        raise_err(ERR_DUPLICATE_SIGNUP, "Volunteer is already signed up.")
    s["signups"].append({
        "volunteer_email": email,
        "volunteer_name": name,
        "signed_up_at": now(),
    })
    touch(s)
    return success_object(shift_json(s), status=201)


@bp.route("/volunteer-shifts/<sid>/withdraw", methods=["POST"])
def withdraw(sid):
    _, role = authenticate()
    require_role(role, SIGNUP_ROLES)
    s = _get_shift_or_404(sid)
    body = get_body()
    email = req_str(body, "volunteer_email")
    before = len(s["signups"])
    s["signups"] = [x for x in s["signups"] if x["volunteer_email"] != email]
    if len(s["signups"]) == before:
        raise_err(ERR_VALIDATION, "Volunteer has no signup on this shift.")
    touch(s)
    return success_object(shift_json(s))
