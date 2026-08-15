"""Exclusion-list screening endpoints (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, current_date, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import exclusion_screening_view
from services import invalidate_sealed_packages, refresh_employee_derived, touch
from util import as_date, as_enum, as_str, body, pagination_args, parse_ymd, required

bp = Blueprint("exclusion_screenings", __name__, url_prefix="/licensing")

LIST_SOURCES = ("OIG_LEIE", "SAM_GSA", "STATE_MEDICAID")
SCREENING_OUTCOMES = ("CLEAR", "FLAGGED")


@bp.post("/employees/<eid>/exclusion-screenings")
def create_screening(eid):
    user_id, role = auth(["ComplianceOfficer"])
    emp = DB["employees"].get(eid)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    data = body()
    list_source = as_enum(required(data, "list_source"), "list_source", LIST_SOURCES)
    screened = as_date(required(data, "screened_on"), "screened_on")
    outcome = as_enum(required(data, "outcome"), "outcome", SCREENING_OUTCOMES)
    if screened > current_date():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "screened_on must not be in the future"
        )

    valid_until = None
    if outcome == "CLEAR":
        valid_until = screened + timedelta(days=30)
        # Clear windows cannot stack for the same employee and list: an existing
        # CLOSED_CLEAR window containing the new screened_on (inclusive at both
        # ends) rejects the creation.
        for scr in DB["exclusion_screenings"].values():
            if (
                scr["employee_id"] == eid
                and scr["list_source"] == list_source
                and scr["status"] == "CLOSED_CLEAR"
            ):
                win_start = parse_ymd(scr["screened_on"])
                win_end = parse_ymd(scr["valid_until"])
                if win_start <= screened <= win_end:
                    raise ApiError(
                        "ERR_SCREENING_WINDOW_OVERLAP", 422,
                        "CLEAR screening falls inside an existing CLOSED_CLEAR validity window",
                    )

    ts = now_iso()
    scr = {
        "id": new_id(),
        "employee_id": eid,
        "list_source": list_source,
        "screened_on": screened.isoformat(),
        "outcome": outcome,
        "status": "CLOSED_CLEAR" if outcome == "CLEAR" else "UNDER_REVIEW",
        "valid_until": valid_until.isoformat() if valid_until else None,
        "created_by_user_id": user_id,
        "resolved_by_user_id": None,
        "resolution_note": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["exclusion_screenings"][scr["id"]] = scr
    # Either outcome re-derives the employee's posture and authorization.
    refresh_employee_derived(emp, bump=True)
    invalidate_sealed_packages(eid, screened)
    return ok(exclusion_screening_view(scr), status=201)


@bp.get("/employees/<eid>/exclusion-screenings")
def list_screenings(eid):
    auth(ALL_ROLES)
    if eid not in DB["employees"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    limit, offset = pagination_args()
    items = sorted(
        (s for s in DB["exclusion_screenings"].values() if s["employee_id"] == eid),
        key=lambda x: x["created_at"],
    )
    status = request.args.get("status")
    list_source = request.args.get("list_source")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if list_source is not None:
        items = [s for s in items if s["list_source"] == list_source]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([exclusion_screening_view(x) for x in page], total, limit, offset)


def _get_screening_or_404(sid):
    scr = DB["exclusion_screenings"].get(sid)
    if scr is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Exclusion screening not found")
    return scr


def _resolve_guard(scr, user_id):
    if scr["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Screening in {scr['status']} cannot be resolved",
        )
    if user_id == scr["created_by_user_id"]:
        raise ApiError(
            "ERR_SOD_SAME_USER", 403,
            "Resolver must differ from the screening's recorder",
        )


@bp.post("/exclusion-screenings/<sid>/confirm-match")
def confirm_match(sid):
    user_id, role = auth(["ComplianceOfficer"])
    scr = _get_screening_or_404(sid)
    _resolve_guard(scr, user_id)
    scr["status"] = "CONFIRMED_MATCH"
    scr["resolved_by_user_id"] = user_id
    touch(scr)
    emp = DB["employees"][scr["employee_id"]]
    refresh_employee_derived(emp, bump=True)
    return ok(exclusion_screening_view(scr))


@bp.post("/exclusion-screenings/<sid>/clear-false-positive")
def clear_false_positive(sid):
    user_id, role = auth(["ComplianceOfficer"])
    scr = _get_screening_or_404(sid)
    data = body()
    resolution_note = None
    if "resolution_note" in data and data["resolution_note"] is not None:
        resolution_note = as_str(data["resolution_note"], "resolution_note")
    _resolve_guard(scr, user_id)
    scr["status"] = "CLEARED_FALSE_POSITIVE"
    scr["resolved_by_user_id"] = user_id
    scr["resolution_note"] = resolution_note
    touch(scr)
    emp = DB["employees"][scr["employee_id"]]
    refresh_employee_derived(emp, bump=True)
    return ok(exclusion_screening_view(scr))
