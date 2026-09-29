"""ScreeningRequest endpoints."""

from flask import Blueprint

from db import clock_iso, db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_SHELTER_MANAGER,
                        acting_staff_id, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_call, get_client, get_screening,
                           get_shelter, get_staff, insert, list_page)
from services import cascade, derive
from validation import (date_out, get_body, opt_str, q_enum, q_str, req_date, req_enum,
                        req_str)

bp = Blueprint("screening", __name__)

SCREENING_STATUSES = ("PENDING", "APPROVED", "DENIED", "WAITLISTED", "ADMITTED", "EXPIRED")
DECISIONS = ("APPROVE", "DENY", "WAITLIST")
READ_ROLES = (ROLE_SHELTER_MANAGER, ROLE_HOTLINE_ADVOCATE, ROLE_AGENCY_ADMIN)


@bp.post("/screening-requests")
def create_screening():
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    body = get_body()
    client_id = req_str(body, "client_id")
    call_id = req_str(body, "hotline_call_id")
    shelter_id = req_str(body, "requested_shelter_id")
    entry_date = req_date(body, "requested_entry_date")

    client = get_client(client_id)
    call = get_call(call_id)
    shelter = get_shelter(shelter_id)

    if call["client_id"] != client["id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH",
                       "the hotline call belongs to a different client")
    if call["status"] not in ("RISK_ASSESSED", "SCREENING_REFERRED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the hotline call has not been risk-assessed")

    request_row = insert("screening_requests", {
        "client_id": client["id"],
        "hotline_call_id": call["id"],
        "requested_shelter_id": shelter["id"],
        "created_by_staff_id": acting_staff_id(user_id, role),
        "assigned_advocate_id": None,
        "offered_shelter_unit_id": None,
        "household_size": client["household_size"],
        "minor_children_count": client["minor_children_count"],
        "accessibility_required": client["accessibility_required"],
        "requested_entry_date": date_out(entry_date),
        "status": "PENDING",
        "waitlist_position": None,
        "promoted_from_waitlist": False,
        "denial_reason": None,
        "decided_at": None,
    })
    return created(public(request_row))


@bp.get("/screening-requests/<request_id>")
def read_screening(request_id):
    auth(READ_ROLES)
    return ok(public(get_screening(request_id)))


@bp.get("/screening-requests")
def list_screenings():
    auth(READ_ROLES)
    filters = {
        "client_id": q_str("client_id"),
        "hotline_call_id": q_str("hotline_call_id"),
        "requested_shelter_id": q_str("requested_shelter_id"),
        "created_by_staff_id": q_str("created_by_staff_id"),
        "assigned_advocate_id": q_str("assigned_advocate_id"),
        "offered_shelter_unit_id": q_str("offered_shelter_unit_id"),
        "status": q_enum("status", SCREENING_STATUSES),
    }
    return list_page(by_created(filtered("screening_requests", filters)))


@bp.post("/screening-requests/<request_id>/decide")
def decide_screening(request_id):
    user_id, role = auth((ROLE_SHELTER_MANAGER,))
    request_row = get_screening(request_id)

    actor = acting_staff_id(user_id, role)
    if actor is not None and request_row["created_by_staff_id"] == actor:
        raise ApiError("ERR_SELF_DECISION_FORBIDDEN",
                       "the creator of a screening request may not decide it")

    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    advocate_id = None
    denial_reason = None
    if decision in ("APPROVE", "WAITLIST"):
        advocate_id = req_str(body, "assigned_advocate_id")
    else:
        denial_reason = req_str(body, "denial_reason", 1, 2000)

    advocate = get_staff(advocate_id) if advocate_id is not None else None

    if request_row["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PENDING screening request may be decided")

    if decision == "APPROVE":
        if advocate["wellness_posture"] == "FROZEN":
            raise ApiError("ERR_ADVOCATE_FROZEN")
        shelter = db.shelters.get(request_row["requested_shelter_id"])
        if shelter is not None and shelter["capacity_posture"] == "FULL":
            raise ApiError("ERR_SHELTER_FULL")
        if advocate["active_caseload_count"] >= advocate["max_caseload"]:
            raise ApiError("ERR_CASELOAD_LIMIT_EXCEEDED")
        request_row["status"] = "APPROVED"
        request_row["assigned_advocate_id"] = advocate["id"]
        request_row["decided_at"] = clock_iso()
        touch(request_row)
        derive.recompute_staff(advocate, force=True)
    elif decision == "WAITLIST":
        if advocate["wellness_posture"] == "FROZEN":
            raise ApiError("ERR_ADVOCATE_FROZEN")
        request_row["status"] = "WAITLISTED"
        request_row["assigned_advocate_id"] = advocate["id"]
        request_row["decided_at"] = clock_iso()
        request_row["waitlist_position"] = cascade.waitlist_position_for(request_row)
        touch(request_row)
    else:
        request_row["status"] = "DENIED"
        request_row["denial_reason"] = denial_reason
        request_row["decided_at"] = clock_iso()
        touch(request_row)

    return ok(public(request_row))
