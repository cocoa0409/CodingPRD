"""Specified employee list endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_INVALID_EFFECTIVE_DATE,
    ERR_DRAFT_LIST_EXISTS,
    ERR_LIST_STATE_INVALID,
    ERR_DUPLICATE_MEMBER,
    ERR_CROSS_PLAN_REFERENCE,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_date,
    req_int,
    req_enum,
    get_or_404,
    stamp_new,
    touch,
    compute_scheduled_payment_date,
)
from util import fmt_date, parse_date

bp = Blueprint("specified_lists", __name__)

BASES = {"OFFICER", "FIVE_PERCENT_OWNER", "COMPENSATION_THRESHOLD"}


def list_view(lst):
    return {
        "id": lst["id"],
        "created_at": lst["created_at"],
        "updated_at": lst["updated_at"],
        "version": lst["version"],
        "plan_id": lst["plan_id"],
        "identification_date": lst["identification_date"],
        "effective_date": lst["effective_date"],
        "status": lst["status"],
        "members": list(lst["members"]),
        "officer_cap_count": lst["officer_cap_count"],
    }


@bp.post("/api/specified-employee-lists")
def create_list():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    id_date = req_date(data, "identification_date")
    eff_date = req_date(data, "effective_date")
    expected = req_int(data, "expected_plan_version")

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if expected != plan["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plan_version does not match current Plan.version")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to create a specified-employee list")

    if not (eff_date > id_date and eff_date <= id_date + timedelta(days=120)):
        raise_err(ERR_INVALID_EFFECTIVE_DATE, "effective_date must be in (identification_date, identification_date + 120 days]")

    for lst in db.specified_employee_lists.values():
        if lst["plan_id"] == plan_id and lst["status"] == "DRAFT":
            raise_err(ERR_DRAFT_LIST_EXISTS, "A DRAFT specified-employee list already exists for the plan")

    lst = stamp_new(
        {
            "plan_id": plan_id,
            "identification_date": fmt_date(id_date),
            "effective_date": fmt_date(eff_date),
            "status": "DRAFT",
            "members": [],
            "officer_cap_count": None,
        }
    )
    db.specified_employee_lists[lst["id"]] = lst
    touch(plan)
    return ok_object(list_view(lst), 201)


@bp.get("/api/specified-employee-lists")
def list_lists():
    user_context()
    items = list(db.specified_employee_lists.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [l for l in items if l["plan_id"] == plan_id]
    return _list_response([list_view(l) for l in items], request.args)


@bp.get("/api/specified-employee-lists/<listId>")
def get_list(listId):
    user_context()
    lst = get_or_404(db.specified_employee_lists, listId, "SpecifiedEmployeeList")
    return ok_object(list_view(lst))


@bp.post("/api/specified-employee-lists/<listId>/members")
def add_member(listId):
    data = body()
    from errors import ERR_INVALID_REQUEST

    participant_id = data.get("participant_id")
    if not isinstance(participant_id, str) or not participant_id:
        raise_err(ERR_INVALID_REQUEST, "participant_id is required and must be a string")
    basis = req_enum(data, "basis", BASES)
    comp = req_int(data, "annual_compensation_cents", lo=0)

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    lst = get_or_404(db.specified_employee_lists, listId, "SpecifiedEmployeeList")

    if lst["status"] != "DRAFT":
        raise_err(ERR_LIST_STATE_INVALID, "Member add requires a DRAFT list")
    participant = get_or_404(db.participants, participant_id, "Participant")
    for m in lst["members"]:
        if m["participant_id"] == participant_id:
            raise_err(ERR_DUPLICATE_MEMBER, "Participant already has a member row in this list")
    if participant["plan_id"] != lst["plan_id"]:
        raise_err(ERR_CROSS_PLAN_REFERENCE, "Member must be a participant of the list's plan")

    lst["members"].append(
        {
            "participant_id": participant_id,
            "basis": basis,
            "annual_compensation_cents": comp,
            "is_specified": None,
            "exclusion_reason": None,
        }
    )
    touch(lst)
    return ok_object(list_view(lst), 201)


@bp.post("/api/specified-employee-lists/<listId>/finalize")
def finalize_list(listId):
    body()
    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    lst = get_or_404(db.specified_employee_lists, listId, "SpecifiedEmployeeList")
    if lst["status"] != "DRAFT":
        raise_err(ERR_LIST_STATE_INVALID, "Finalize requires a DRAFT list")

    plan = db.plans[lst["plan_id"]]

    eligible = [
        p
        for p in db.participants.values()
        if p["plan_id"] == lst["plan_id"] and p["status"] in ("ACTIVE", "SEPARATION_REVIEW", "SEPARATED")
    ]
    officer_cap = min(50, (len(eligible) * 10) // 100)
    lst["officer_cap_count"] = officer_cap

    # Rank OFFICER members by comp DESC, tie-break Participant.created_at ASC
    officer_members = [m for m in lst["members"] if m["basis"] == "OFFICER"]
    officer_members.sort(
        key=lambda m: (-m["annual_compensation_cents"], db.participants[m["participant_id"]]["created_at"])
    )
    for rank, m in enumerate(officer_members, start=1):
        if rank <= officer_cap:
            m["is_specified"] = True
            m["exclusion_reason"] = None
        else:
            m["is_specified"] = False
            m["exclusion_reason"] = "OFFICER_CAP_EXCEEDED"

    for m in lst["members"]:
        if m["basis"] == "COMPENSATION_THRESHOLD":
            if m["annual_compensation_cents"] >= plan["officer_comp_threshold_cents"]:
                m["is_specified"] = True
                m["exclusion_reason"] = None
            else:
                m["is_specified"] = False
                m["exclusion_reason"] = "BELOW_COMP_THRESHOLD"
        elif m["basis"] == "FIVE_PERCENT_OWNER":
            m["is_specified"] = True
            m["exclusion_reason"] = None

    # Capture pre-update flags to detect false->true flips
    prior_flags = {p["id"]: p["is_specified_employee"] for p in db.participants.values() if p["plan_id"] == lst["plan_id"]}

    # Supersede prior FINALIZED lists of the same plan
    for other in db.specified_employee_lists.values():
        if other["plan_id"] == lst["plan_id"] and other["status"] == "FINALIZED" and other["id"] != lst["id"]:
            other["status"] = "SUPERSEDED"
            touch(other)

    # Reset every plan participant to False, then set specified members True
    specified_ids = {m["participant_id"] for m in lst["members"] if m["is_specified"]}
    for p in db.participants.values():
        if p["plan_id"] != lst["plan_id"]:
            continue
        new_flag = p["id"] in specified_ids
        if p["is_specified_employee"] != new_flag:
            p["is_specified_employee"] = new_flag
            touch(p)

    # Cascade: newly specified participants' SCHEDULED SEPARATION distributions
    for p in db.participants.values():
        if p["plan_id"] != lst["plan_id"]:
            continue
        if not prior_flags.get(p["id"], False) and p["is_specified_employee"]:
            for req in db.distribution_requests.values():
                if (
                    req["participant_id"] == p["id"]
                    and req["status"] == "SCHEDULED"
                    and req["event_type"] == "SEPARATION"
                    and plan["six_month_delay_enabled"]
                ):
                    req["scheduled_payment_date"] = fmt_date(compute_scheduled_payment_date(req))
                    touch(req)

    lst["status"] = "FINALIZED"
    touch(lst)
    return ok_object(list_view(lst))
