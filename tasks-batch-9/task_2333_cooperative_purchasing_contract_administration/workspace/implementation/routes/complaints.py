"""Member complaints and supplier performance monitoring (PRD 3.9)."""

from flask import Blueprint

import calc
import services
from calc import num
from db import (add_days, create_row, db, get_dt, logical_now, ordered,
                serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, actor_id, commit,
                        require_roles, touch)
from response import created_response, object_response
from routes.common import (COMPLAINT_CATEGORY, COMPLAINT_SEVERITY,
                           COMPLAINT_STATUS, fetch, list_endpoint)
from validation import json_body, read_id, read_str

bp = Blueprint("complaints", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
              ROLE_AUDITOR)
INVESTIGATION_ACTIONS = ("OPEN_INVESTIGATION", "DISMISS")
DECISION_ACTIONS = ("SUBSTANTIATE", "CLOSE")
APPEAL_ACTIONS = ("FILE_APPEAL",)
APPEAL_DECISION_ACTIONS = ("OVERTURN", "UPHOLD")


# =========================================================================
# filing and reads
# =========================================================================

@bp.route("/coop/complaints", methods=["POST"])
@require_roles(ROLE_MEMBER)
def create_complaint():
    body = json_body(
        allowed=("contract_id", "member_agency_id", "related_usage_id",
                 "severity", "category", "narrative"),
        required=("contract_id", "member_agency_id", "severity", "category",
                  "narrative"),
    )
    contract_id = read_id(body, "contract_id", required=True)
    member_id = read_id(body, "member_agency_id", required=True)
    usage_id = read_id(body, "related_usage_id")
    severity = read_str(body, "severity", required=True, enum=COMPLAINT_SEVERITY)
    category = read_str(body, "category", required=True, enum=COMPLAINT_CATEGORY)
    narrative = read_str(body, "narrative", required=True, min_len=1, max_len=2000)

    # 5. body foreign keys in entity field order
    fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    usage = None
    if usage_id is not None:
        usage = fetch(db.usages, usage_id, "ERR_USAGE_NOT_FOUND")

    # 7. the acting member must file for itself
    if actor_id() != member_id:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the member_agency_id named in the body")

    # 36. a cited order must belong to the same member and contract
    if usage is not None:
        if usage["contract_id"] != contract_id or usage[
                "member_agency_id"] != member_id:
            fail("ERR_USAGE_PAIR_MISMATCH",
                 "the cited order does not belong to this member and contract")

    row = create_row(
        db.complaints,
        contract_id=contract_id,
        member_agency_id=member_id,
        related_usage_id=usage_id,
        severity=severity,
        category=category,
        narrative=narrative,
        status="INTAKE",
        deduction_points=None,
        points_reversed=False,
        investigator_user_id=None,
        adjudicator_user_id=None,
        substantiated_at=None,
        appeal_filed_at=None,
        appeal_deadline_at=None,
    )
    set_dt(row, "substantiated_at", None)
    set_dt(row, "appeal_filed_at", None)
    set_dt(row, "appeal_deadline_at", None)
    return created_response(serialize(row))


@bp.route("/coop/complaints", methods=["GET"])
@require_roles(*READ_ROLES)
def list_complaints():
    return list_endpoint(
        lambda: ordered(db.complaints),
        {"contract_id": ("contract_id", None),
         "member_agency_id": ("member_agency_id", None),
         "related_usage_id": ("related_usage_id", None),
         "status": ("status", COMPLAINT_STATUS),
         "severity": ("severity", COMPLAINT_SEVERITY)},
    )


@bp.route("/coop/complaints/<complaint_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_complaint(complaint_id):
    row = fetch(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
    return object_response(serialize(row))


# =========================================================================
# investigation fork
# =========================================================================

@bp.route("/coop/complaints/<complaint_id>/investigation", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def investigation(complaint_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True, enum=INVESTIGATION_ACTIONS)
    read_str(body, "note")

    complaint = fetch(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")

    # 8. the investigator may not adjudicate its own case
    if action == "DISMISS":
        _require_distinct(actor_id(), complaint["investigator_user_id"],
                          "the investigator may not decide the case")

    # 12. from-state on the complaint lifecycle
    status = complaint["status"]
    expected = {"OPEN_INVESTIGATION": ("INTAKE",),
                "DISMISS": ("UNDER_INVESTIGATION",)}[action]
    if status not in expected:
        fail("ERR_COMPLAINT_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    if action == "OPEN_INVESTIGATION":
        complaint["status"] = "UNDER_INVESTIGATION"
        complaint["investigator_user_id"] = actor_id()
    else:
        complaint["status"] = "DISMISSED"
        complaint["adjudicator_user_id"] = actor_id()

    touch(complaint)
    commit()
    return object_response(serialize(complaint))


def _require_distinct(actor, other, detail):
    if other is not None and actor == other:
        fail("ERR_SEGREGATION_OF_DUTIES", detail)


# =========================================================================
# substantiation and closure
# =========================================================================

@bp.route("/coop/complaints/<complaint_id>/decision", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def decision(complaint_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True, enum=DECISION_ACTIONS)
    read_str(body, "note")

    complaint = fetch(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")

    # 8. the investigator may not adjudicate its own case
    if action == "SUBSTANTIATE":
        _require_distinct(actor_id(), complaint["investigator_user_id"],
                          "the investigator may not substantiate the case")

    # 12. from-state on the complaint lifecycle
    status = complaint["status"]
    expected = {"SUBSTANTIATE": ("UNDER_INVESTIGATION",),
                "CLOSE": ("SUBSTANTIATED",)}[action]
    if status not in expected:
        fail("ERR_COMPLAINT_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    contract = db.contracts[complaint["contract_id"]]
    supplier = db.suppliers[contract["supplier_id"]]

    # 26. the supplier who would absorb the deduction is not DEBARRED
    if action == "SUBSTANTIATE" and supplier["qualification_status"] == "DEBARRED":
        fail("ERR_SUPPLIER_DEBARRED", "the contract's supplier is DEBARRED")

    # 49. closure waits for the appeal window to elapse
    if action == "CLOSE":
        deadline = get_dt(complaint, "appeal_deadline_at")
        if deadline is not None and not logical_now() > deadline:
            fail("ERR_APPEAL_WINDOW_OPEN", "the appeal window has not elapsed")

    if action == "SUBSTANTIATE":
        now = logical_now()
        complaint["status"] = "SUBSTANTIATED"
        complaint["adjudicator_user_id"] = actor_id()
        complaint["deduction_points"] = num(
            calc.DEDUCTION_POINTS_BY_SEVERITY[complaint["severity"]])
        set_dt(complaint, "substantiated_at", now)
        set_dt(complaint, "appeal_deadline_at",
               add_days(now, calc.APPEAL_WINDOW_DAYS))
        touch(complaint)
        # Five hops: points, score, tier, supplier standing, contract opinions.
        services.recompute_supplier_performance(supplier)
    else:
        complaint["status"] = "CLOSED"
        touch(complaint)
        services.recompute_supplier_performance(supplier)

    commit()
    return object_response(serialize(complaint))


# =========================================================================
# appeal
# =========================================================================

@bp.route("/coop/complaints/<complaint_id>/appeal", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def appeal(complaint_id):
    body = json_body(allowed=("action", "note"), required=())
    read_str(body, "action", enum=APPEAL_ACTIONS)
    read_str(body, "note")

    complaint = fetch(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
    contract = db.contracts[complaint["contract_id"]]

    # 7. only the supplier that absorbed the deduction may appeal
    if actor_id() != contract["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the contract's supplier_id")

    # 12. from-state on the complaint lifecycle
    if complaint["status"] != "SUBSTANTIATED":
        fail("ERR_COMPLAINT_INVALID_STATE",
             "FILE_APPEAL is not a declared transition out of %s"
             % complaint["status"])

    # 48. the appeal window is inclusive at its boundary
    now = logical_now()
    deadline = get_dt(complaint, "appeal_deadline_at")
    if deadline is not None and now > deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED", "the appeal window has closed")

    complaint["status"] = "APPEALED"
    set_dt(complaint, "appeal_filed_at", now)
    touch(complaint)
    commit()
    return object_response(serialize(complaint))


@bp.route("/coop/complaints/<complaint_id>/appeal-decision", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def appeal_decision(complaint_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True,
                      enum=APPEAL_DECISION_ACTIONS)
    read_str(body, "note")

    complaint = fetch(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")

    # 8. the adjudicator may not hear the appeal against its own decision
    _require_distinct(actor_id(), complaint["adjudicator_user_id"],
                      "the adjudicator may not decide the appeal")

    # 12. from-state on the complaint lifecycle
    if complaint["status"] != "APPEALED":
        fail("ERR_COMPLAINT_INVALID_STATE",
             "%s is not a declared transition out of %s"
             % (action, complaint["status"]))

    contract = db.contracts[complaint["contract_id"]]
    supplier = db.suppliers[contract["supplier_id"]]

    if action == "OVERTURN":
        complaint["status"] = "OVERTURNED"
        complaint["points_reversed"] = True
    else:
        complaint["status"] = "CLOSED"

    touch(complaint)
    # The exact compensating action: the score is recomputed, never patched.
    services.recompute_supplier_performance(supplier)
    commit()
    return object_response(serialize(complaint))
