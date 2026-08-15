"""ViolationCase endpoints: manual open, investigation action chain."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE
from errors import (err, ERR_CASE_ALREADY_OPEN, ERR_INVALID_STATE)
from middleware import require_roles
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           apply_flags, compute_severity, sanction_for_score,
                           VIOLATION_TYPES)
from util import Body, fmt_ts

bp = Blueprint("cases", __name__)

ROLES = ("ComplianceOfficer", "LegalAdmin")

# action -> (allowed from-states, to-state)
ACTIONS = {
    "BEGIN_INVESTIGATION": (("OPENED",), "UNDER_INVESTIGATION"),
    "ESCALATE": (("UNDER_INVESTIGATION",), "ESCALATED"),
    "DEESCALATE": (("ESCALATED",), "UNDER_INVESTIGATION"),
    "SUBSTANTIATE": (("UNDER_INVESTIGATION", "ESCALATED"), "SUBSTANTIATED"),
    "UNFOUND": (("UNDER_INVESTIGATION", "ESCALATED"), "UNFOUNDED"),
    "RECORD_SANCTION": (("SUBSTANTIATED",), "SANCTION_RECORDED"),
    "CLOSE": (("SANCTION_RECORDED", "UNFOUNDED"), "CLOSED"),
}


@bp.post("/violation-cases")
def create_case():
    require_roles("ComplianceOfficer")
    body = Body()
    person_id = body.get_str("covered_person_id")
    vtype = body.get_enum("violation_type", VIOLATION_TYPES)
    tcid = body.get_str("trade_confirmation_id", required=False)
    note = body.get_str("note", required=False)
    # Body FK existence before the schema flush.
    person = None
    if person_id is not None:
        person = get_or_404("covered_persons", person_id, "covered person")
    if tcid is not None:
        get_or_404("trade_confirmations", tcid, "trade confirmation")
        # One confirmation, one open case.
        if any(c["trade_confirmation_id"] == tcid and c["status"] != "CLOSED"
               for c in STORE.violation_cases.values()):
            raise err(ERR_CASE_ALREADY_OPEN,
                      "a non-CLOSED ViolationCase already references this trade confirmation")
    body.flush()
    c = new_entity()
    c.update({
        "covered_person_id": person_id,
        "trade_confirmation_id": tcid,
        "violation_type": vtype,
        "source": "MANUAL",
        "status": "OPENED",
        "severity_score": None,
        "sanction": None,
        "sanction_recorded_at": None,
        "note": note,
        "_sanction_recorded_dt": None,
    })
    STORE.violation_cases[c["id"]] = c
    apply_flags(person)  # compliance_hold recomputed on the spot
    return success(serialize(c), 201)


@bp.get("/violation-cases/<cid>")
def get_case(cid):
    require_roles(*ROLES)
    c = get_or_404("violation_cases", cid, "violation case")
    return success(serialize(c))


@bp.get("/violation-cases")
def list_cases():
    require_roles(*ROLES)
    items = sort_created(STORE.violation_cases.values())
    person_id = request.args.get("covered_person_id")
    tcid = request.args.get("trade_confirmation_id")
    status = request.args.get("status")
    if person_id is not None:
        items = [c for c in items if c["covered_person_id"] == person_id]
    if tcid is not None:
        items = [c for c in items if c["trade_confirmation_id"] == tcid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([serialize(c) for c in items])


@bp.post("/violation-cases/<cid>/action")
def case_action(cid):
    require_roles("ComplianceOfficer")
    c = get_or_404("violation_cases", cid, "violation case")
    body = Body()
    action = body.get_enum("action", set(ACTIONS))
    from_states = None
    to_state = None
    if action is not None:
        from_states, to_state = ACTIONS[action]
        if c["status"] not in from_states:
            raise err(ERR_INVALID_STATE,
                      f"action {action} is not valid from state {c['status']}")
    body.flush()
    prior_status = c["status"]
    c["status"] = to_state
    if action == "SUBSTANTIATE":
        c["severity_score"] = compute_severity(c)
    elif action == "RECORD_SANCTION":
        c["sanction"] = sanction_for_score(c["severity_score"])
        now = STORE.clock
        c["sanction_recorded_at"] = fmt_ts(now)
        c["_sanction_recorded_dt"] = now
        if c["sanction"] in ("SUSPENSION_30D", "SUSPENSION_90D"):
            person = STORE.covered_persons.get(c["covered_person_id"])
            if person is not None:
                days = 30 if c["sanction"] == "SUSPENSION_30D" else 90
                person["status"] = "SUSPENDED"
                until = now + timedelta(days=days)
                person["suspended_until"] = fmt_ts(until)
                person["_suspended_until_dt"] = until
                touch(person)
    elif action == "CLOSE":
        if prior_status == "UNFOUNDED":
            conf = (STORE.trade_confirmations.get(c["trade_confirmation_id"])
                    if c["trade_confirmation_id"] else None)
            if conf is not None and conf["status"] == "FLAGGED":
                conf["status"] = "CLEARED"
                touch(conf)
        person = STORE.covered_persons.get(c["covered_person_id"])
        if person is not None:
            apply_flags(person)  # compliance_hold recomputed after close
    touch(c)
    return success(serialize(c))
