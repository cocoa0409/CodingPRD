"""Memberships and panel waitlist entries."""
from flask import Blueprint, g

import calc
import constants as C
import serialize
import svc_membership
import validate as V
from auth import begin, parent_family_scope, require_child_owner, require_membership_owner
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, new_row, touch
from timeutil import last_day_of_month

bp = Blueprint("memberships", __name__)


# ================================================================ Membership
@bp.post("/peds/memberships")
def create_membership():
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_CARE_COORDINATOR])           # RUNG 1, 2
    body = V.json_body()
    child_id = V.req_string(body, "child_id")                         # RUNG 4 p9
    plan_id = V.req_string(body, "plan_id")
    physician_id = V.req_string(body, "physician_id")
    V.req_string(body, "start_date")
    expected_family_version = V.req_int(body, "expected_family_version")
    start_date = V.req_date(body, "start_date")                       # RUNG 5 p12

    today = db.today()
    V.date_range(                                                     # RUNG 5 p13
        today <= start_date <= last_day_of_month(today),
        "start_date must fall between today and the last day of the current month.",
    )

    child = db.children.get(child_id)                                 # RUNG 6 p15
    if child is None:
        raise ApiError("ERR_CHILD_NOT_FOUND")
    plan = db.plans.get(plan_id)                                      # RUNG 6 p16
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    physician = db.physicians.get(physician_id)                       # RUNG 6 p17
    if physician is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND")

    family = db.families.get(child["family_id"])
    if family is None:
        raise ApiError("ERR_FAMILY_NOT_FOUND")

    if expected_family_version != family["version"]:                  # RUNG 9 p21
        raise ApiError("ERR_STALE_VERSION")

    for membership in db.memberships.values():                        # RUNG 15 p32
        if (
            membership["child_id"] == child_id
            and membership["status"] in C.MEMBERSHIP_OCCUPYING_STATUSES
        ):
            raise ApiError("ERR_DUPLICATE_MEMBERSHIP")

    occupancy_t = calc.weighted_occupancy_tenths(physician_id)        # RUNG 16 p34
    candidate_t = calc.tenths(calc.child_slot_weight(child))
    if occupancy_t + candidate_t > calc.tenths(physician["panel_slot_cap"]):
        raise ApiError("ERR_PANEL_CAPACITY_EXCEEDED")

    membership = svc_membership.create_membership(child, plan, physician, start_date, family)
    return object_response(serialize.membership_json(membership), 201)


@bp.get("/peds/memberships")
def list_memberships():
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_PHYSICIAN,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_PARENT,
        ]
    )
    status = V.enum_filter("status", C.MEMBERSHIP_STATUSES)           # RUNG 4 p10
    limit, offset = V.pagination()                                    # RUNG 4 p11
    family_id = V.filter_value("family_id")
    child_id = V.filter_value("child_id")
    plan_id = V.filter_value("plan_id")
    physician_id = V.filter_value("physician_id")
    scope = parent_family_scope()

    rows = []
    for membership in db.memberships.values():
        if family_id is not None and membership["family_id"] != family_id:
            continue
        if child_id is not None and membership["child_id"] != child_id:
            continue
        if plan_id is not None and membership["plan_id"] != plan_id:
            continue
        if physician_id is not None and membership["physician_id"] != physician_id:
            continue
        if status is not None and membership["status"] != status:
            continue
        if scope is not None and membership["family_id"] != scope:
            continue
        rows.append(membership)
    return paginated(rows, serialize.membership_json, limit, offset)


@bp.get("/peds/memberships/<membership_id>")
def read_membership(membership_id):
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_PHYSICIAN,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_PARENT,
        ]
    )
    membership = db.memberships.get(membership_id)                    # RUNG 3 p6
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")
    require_membership_owner(membership)                              # RUNG 7 p19
    return object_response(serialize.membership_json(membership), 200)


@bp.post("/peds/memberships/<membership_id>/cancel")
def cancel_membership(membership_id):
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_CARE_COORDINATOR])
    membership = db.memberships.get(membership_id)                    # RUNG 3 p6
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")

    body = V.json_body()
    V.req_string(body, "effective_date")                              # RUNG 4 p9
    expected_family_version = V.req_int(body, "expected_family_version")
    effective_date = V.req_date(body, "effective_date")               # RUNG 5 p12

    today = db.today()
    V.date_range(                                                     # RUNG 5 p13
        membership["start_date"] <= effective_date,
        "effective_date must be on or after the membership start_date.",
    )
    V.date_range(
        today <= effective_date <= last_day_of_month(today),
        "effective_date must fall between today and the last day of the current month.",
    )

    family = db.families.get(membership["family_id"])
    if family is None:
        raise ApiError("ERR_FAMILY_NOT_FOUND")
    if expected_family_version != family["version"]:                  # RUNG 9 p21
        raise ApiError("ERR_STALE_VERSION")

    if membership["status"] == "CANCELLED":                           # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "The membership is already CANCELLED.")

    svc_membership.cancel_membership(membership, effective_date)
    return object_response(serialize.membership_json(membership), 200)


@bp.post("/peds/memberships/<membership_id>/suspend")
def suspend_membership(membership_id):
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST])
    membership = db.memberships.get(membership_id)                    # RUNG 3 p6
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")
    body = V.json_body()
    reason = V.req_string(body, "reason")                             # RUNG 4 p9

    if membership["status"] != "ACTIVE":                              # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE membership can be suspended.")
    if not svc_membership.has_past_due_issued_invoice(membership["family_id"]):
        raise ApiError("ERR_ENROLLMENT_INVOICE_UNPAID")               # RUNG 10 p24

    membership["status"] = "SUSPENDED"
    membership["suspension_reason"] = reason
    touch(membership, g.touched)
    return object_response(serialize.membership_json(membership), 200)


@bp.post("/peds/memberships/<membership_id>/reinstate")
def reinstate_membership(membership_id):
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST])
    membership = db.memberships.get(membership_id)                    # RUNG 3 p6
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")

    if membership["status"] != "SUSPENDED":                           # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED membership can be reinstated.")
    if svc_membership.has_past_due_issued_invoice(membership["family_id"]):
        raise ApiError("ERR_ENROLLMENT_INVOICE_UNPAID")               # RUNG 10 p24

    membership["status"] = "ACTIVE"
    membership["suspension_reason"] = None
    touch(membership, g.touched)
    return object_response(serialize.membership_json(membership), 200)


# ========================================================= PanelWaitlistEntry
WAITLIST_ROLES = [C.ROLE_PRACTICE_ADMIN, C.ROLE_CARE_COORDINATOR, C.ROLE_PARENT]


@bp.post("/peds/panel-waitlist-entries")
def create_waitlist_entry():
    begin(WAITLIST_ROLES)
    body = V.json_body()
    physician_id = V.req_string(body, "physician_id")                 # RUNG 4 p9
    child_id = V.req_string(body, "child_id")
    requested_plan_id = V.req_string(body, "requested_plan_id")

    child = db.children.get(child_id)                                 # RUNG 6 p15
    if child is None:
        raise ApiError("ERR_CHILD_NOT_FOUND")
    plan = db.plans.get(requested_plan_id)                            # RUNG 6 p16
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    physician = db.physicians.get(physician_id)                       # RUNG 6 p17
    if physician is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND")

    require_child_owner(child)                                        # RUNG 7 p19

    for entry in db.waitlist_entries.values():                        # RUNG 15 p33
        if (
            entry["physician_id"] == physician_id
            and entry["child_id"] == child_id
            and entry["status"] == "WAITING"
        ):
            raise ApiError("ERR_DUPLICATE_WAITLIST_ENTRY")

    entry = new_row(
        db.waitlist_entries,
        {
            "physician_id": physician_id,
            "child_id": child_id,
            "requested_plan_id": requested_plan_id,
            "promoted_membership_id": None,
            "status": "WAITING",
        },
    )
    return object_response(serialize.waitlist_json(entry), 201)


def _waitlist_family_id(entry):
    child = db.children.get(entry["child_id"])
    return child["family_id"] if child else None


@bp.get("/peds/panel-waitlist-entries")
def list_waitlist_entries():
    begin(WAITLIST_ROLES)
    status = V.enum_filter("status", C.WAITLIST_STATUSES)             # RUNG 4 p10
    limit, offset = V.pagination()                                    # RUNG 4 p11
    physician_id = V.filter_value("physician_id")
    child_id = V.filter_value("child_id")
    requested_plan_id = V.filter_value("requested_plan_id")
    promoted_membership_id = V.filter_value("promoted_membership_id")
    scope = parent_family_scope()

    rows = []
    for entry in db.waitlist_entries.values():
        if physician_id is not None and entry["physician_id"] != physician_id:
            continue
        if child_id is not None and entry["child_id"] != child_id:
            continue
        if requested_plan_id is not None and entry["requested_plan_id"] != requested_plan_id:
            continue
        if (
            promoted_membership_id is not None
            and entry["promoted_membership_id"] != promoted_membership_id
        ):
            continue
        if status is not None and entry["status"] != status:
            continue
        if scope is not None and _waitlist_family_id(entry) != scope:
            continue
        rows.append(entry)
    return paginated(rows, serialize.waitlist_json, limit, offset)


@bp.get("/peds/panel-waitlist-entries/<waitlist_entry_id>")
def read_waitlist_entry(waitlist_entry_id):
    begin(WAITLIST_ROLES)
    entry = db.waitlist_entries.get(waitlist_entry_id)                # RUNG 3 p8
    if entry is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    child = db.children.get(entry["child_id"])
    if child is not None:
        require_child_owner(child)                                    # RUNG 7 p19
    return object_response(serialize.waitlist_json(entry), 200)


@bp.post("/peds/panel-waitlist-entries/<waitlist_entry_id>/withdraw")
def withdraw_waitlist_entry(waitlist_entry_id):
    begin(WAITLIST_ROLES)
    entry = db.waitlist_entries.get(waitlist_entry_id)                # RUNG 3 p8
    if entry is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    child = db.children.get(entry["child_id"])
    if child is not None:
        require_child_owner(child)                                    # RUNG 7 p19
    if entry["status"] != "WAITING":                                  # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a WAITING entry can be withdrawn.")

    entry["status"] = "WITHDRAWN"
    touch(entry, g.touched)
    return object_response(serialize.waitlist_json(entry), 200)
