"""School, camp and sports form requests."""
from datetime import timedelta

from flask import Blueprint, g

import constants as C
import serialize
import svc_form
import validate as V
from auth import begin, parent_family_scope, require_membership_owner, require_physician_clinical_owner
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, new_row, touch

bp = Blueprint("forms", __name__)

FORM_READ_ROLES = [
    C.ROLE_PRACTICE_ADMIN,
    C.ROLE_CARE_COORDINATOR,
    C.ROLE_PHYSICIAN,
    C.ROLE_PARENT,
]


def _membership_family(membership_id):
    membership = db.memberships.get(membership_id)
    return membership["family_id"] if membership else None


@bp.post("/peds/form-requests")
def create_form_request():
    begin([C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN, C.ROLE_PARENT])
    body = V.json_body()
    membership_id = V.req_string(body, "membership_id")               # RUNG 4 p9
    form_type = V.req_string(body, "form_type")
    V.req_string(body, "needed_by_date")
    V.enum_member(form_type, C.FORM_TYPES, "form_type")               # RUNG 4 p10
    needed_by_date = V.req_date(body, "needed_by_date")               # RUNG 5 p12

    membership = db.memberships.get(membership_id)                    # RUNG 6 p18
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")

    require_membership_owner(membership)                              # RUNG 7 p19

    plan = db.plans.get(membership["plan_id"])
    requested_at = db.now()
    sla_hours = plan["form_sla_hours"] if plan else 0
    due_at = requested_at + timedelta(hours=sla_hours)

    blocked_reason = svc_form.evaluate_gate(membership)
    form = new_row(
        db.form_requests,
        {
            "membership_id": membership_id,
            "child_id": membership["child_id"],
            "form_type": form_type,
            "needed_by_date": needed_by_date,
            "requested_at": requested_at,
            "due_at": due_at,
            "issued_at": None,
            "sla_met": None,
            "blocked_reason": blocked_reason,
            "status": "PENDING" if blocked_reason is None else "BLOCKED",
        },
    )
    # A failing gate produces a BLOCKED row rather than an error; still 201.
    return object_response(serialize.form_request_json(form), 201)


@bp.get("/peds/form-requests")
def list_form_requests():
    begin(FORM_READ_ROLES)
    status = V.enum_filter("status", C.FORM_STATUSES)                 # RUNG 4 p10
    limit, offset = V.pagination()                                    # RUNG 4 p11
    membership_id = V.filter_value("membership_id")
    child_id = V.filter_value("child_id")
    scope = parent_family_scope()

    rows = []
    for form in db.form_requests.values():
        if membership_id is not None and form["membership_id"] != membership_id:
            continue
        if child_id is not None and form["child_id"] != child_id:
            continue
        if status is not None and form["status"] != status:
            continue
        if scope is not None and _membership_family(form["membership_id"]) != scope:
            continue
        rows.append(form)
    return paginated(rows, serialize.form_request_json, limit, offset)


@bp.get("/peds/form-requests/<form_request_id>")
def read_form_request(form_request_id):
    begin(FORM_READ_ROLES)
    form = db.form_requests.get(form_request_id)                      # RUNG 3 p8
    if form is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(form["membership_id"]))  # RUNG 7 p19
    return object_response(serialize.form_request_json(form), 200)


@bp.post("/peds/form-requests/<form_request_id>/issue")
def issue_form_request(form_request_id):
    begin([C.ROLE_PHYSICIAN, C.ROLE_PRACTICE_ADMIN])
    form = db.form_requests.get(form_request_id)                      # RUNG 3 p8
    if form is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    membership = db.memberships.get(form["membership_id"])
    require_physician_clinical_owner(membership)                      # RUNG 7 p19

    if form["status"] == "ISSUED":                                    # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "The form request is already ISSUED.")
    if form["status"] == "BLOCKED":                                   # RUNG 17 p37
        raise ApiError("ERR_FORM_GATE_NOT_MET")

    blocked_reason = svc_form.evaluate_gate(membership)
    if blocked_reason is not None:
        form["status"] = "BLOCKED"
        form["blocked_reason"] = blocked_reason
        touch(form, g.touched)
        return object_response(serialize.form_request_json(form), 200)

    form["status"] = "ISSUED"
    form["issued_at"] = db.now()
    form["sla_met"] = form["issued_at"] <= form["due_at"]
    form["blocked_reason"] = None
    touch(form, g.touched)
    return object_response(serialize.form_request_json(form), 200)


@bp.post("/peds/form-requests/<form_request_id>/recheck")
def recheck_form_request(form_request_id):
    begin([C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN, C.ROLE_PHYSICIAN])
    form = db.form_requests.get(form_request_id)                      # RUNG 3 p8
    if form is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    if form["status"] != "BLOCKED":                                   # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a BLOCKED request can be rechecked.")

    membership = db.memberships.get(form["membership_id"])
    blocked_reason = svc_form.evaluate_gate(membership)
    if blocked_reason is None:
        form["status"] = "PENDING"
        form["blocked_reason"] = None
    else:
        form["blocked_reason"] = blocked_reason
    touch(form, g.touched)
    return object_response(serialize.form_request_json(form), 200)
