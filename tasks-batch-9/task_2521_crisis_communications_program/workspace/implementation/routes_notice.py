"""Stakeholder notices and the audience sequence (PRD 3.6).

Endpoints in this module (5):
  POST   /crisis/stakeholder-notices
  GET    /crisis/stakeholder-notices/{notice_id}
  GET    /crisis/stakeholder-notices
  POST   /crisis/stakeholder-notices/{notice_id}/release
  POST   /crisis/stakeholder-notices/{notice_id}/cancel
"""

from datetime import timedelta

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    D,
    Field,
    authenticate,
    enum_filter,
    fail,
    new_record,
    ok,
    ok_list,
    pagination,
    paged,
    store,
    str_filter,
    touch,
    validate_body,
)

bp = Blueprint("notice", __name__)

NOTICE_STATES = ("QUEUED", "RELEASED", "BLOCKED", "CANCELLED")


def notice_incident(notice):
    incident = store.incidents.get(notice["incident_id"])
    if incident is None:
        fail("ERR_INCIDENT_NOT_FOUND", "The notice's incident no longer resolves.")
    return incident


@bp.post("/crisis/stakeholder-notices")
def create_notice():
    authenticate(("CommsLead",))
    body = validate_body(
        [
            Field("incident_id", "id", required=True),
            Field("statement_id", "id", required=True),
            Field("audience", "enum", required=True, values=L.AUDIENCES),
            Field("estimated_reach", "int", required=True, min=0),
            Field("embargo_until", "datetime", default=None, nullable=True),
        ]
    )
    incident = L.get_incident(body["incident_id"])
    statement = L.get_statement(body["statement_id"])
    L.require_activated(incident)
    L.require_not_frozen(incident)
    notice = new_record(
        {
            "incident_id": incident["id"],
            "statement_id": statement["id"],
            "audience": body["audience"],
            "sequence_rank": L.AUDIENCE_SEQUENCE_RANK[body["audience"]],
            "estimated_reach": body["estimated_reach"],
            "embargo_until": body["embargo_until"],
            "reach_contribution": D("0.00"),
            "state": "QUEUED",
            "released_at": None,
            "priority_override_used": False,
            "cancel_reason": None,
        }
    )
    store.notices[notice["id"]] = notice
    L.refresh(incident)
    return ok(notice, 201)


@bp.get("/crisis/stakeholder-notices/<notice_id>")
def read_notice(notice_id):
    authenticate(ALL_ROLES)
    return ok(L.get_notice(notice_id))


@bp.get("/crisis/stakeholder-notices")
def list_notices():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    statement_id = str_filter("statement_id")
    audience = enum_filter("audience", L.AUDIENCES)
    state = enum_filter("state", NOTICE_STATES)
    rows = list(store.notices.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if statement_id is not None:
        rows = [r for r in rows if r["statement_id"] == statement_id]
    if audience is not None:
        rows = [r for r in rows if r["audience"] == audience]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/stakeholder-notices/<notice_id>/release")
def release_notice(notice_id):
    caller = authenticate(("CommsLead", "LegalCounsel"))
    body = validate_body([Field("priority_override", "bool", default=False)])
    notice = L.get_notice(notice_id)
    # 10. from-state.
    if notice["state"] != "QUEUED":
        fail("ERR_NOTICE_STATE_INVALID", "Only a QUEUED notice may be released.")
    incident = notice_incident(notice)
    # 11. and 12.
    L.require_activated(incident)
    L.require_not_frozen(incident)
    # 16. the carried statement must be published.
    statement = store.statements.get(notice["statement_id"])
    if statement is None or statement["state"] != "PUBLISHED":
        fail("ERR_STATEMENT_NOT_PUBLISHED", "The notice's statement is not PUBLISHED.")
    now = store.now()
    # 21. embargo.
    if notice["embargo_until"] is not None and now < notice["embargo_until"]:
        fail("ERR_EMBARGO_NOT_REACHED", "The notice embargo has not been reached.")
    # 26. audience sequence, with the statutory override as the only bypass.
    unsettled = [
        n
        for n in L.incident_notices(incident["id"])
        if n["sequence_rank"] < notice["sequence_rank"]
        and n["state"] not in ("RELEASED", "CANCELLED")
    ]
    override_applies = (
        body["priority_override"] is True
        and notice["audience"] == "REGULATOR"
        and caller.role == "LegalCounsel"
        and incident["activated_at"] is not None
        and now
        >= incident["activated_at"]
        + timedelta(minutes=L.REGULATORY_OVERRIDE_WINDOW_MINUTES)
    )
    if unsettled and not override_applies:
        fail(
            "ERR_NOTICE_SEQUENCE_VIOLATION",
            "Lower-ranked stakeholder notices on this incident are not yet settled.",
        )
    notice["state"] = "RELEASED"
    notice["released_at"] = now
    notice["reach_contribution"] = L.notice_reach_contribution(notice)
    notice["priority_override_used"] = bool(override_applies and unsettled)
    touch(notice)
    L.refresh(incident)
    touch(incident)
    return ok(notice)


@bp.post("/crisis/stakeholder-notices/<notice_id>/cancel")
def cancel_notice(notice_id):
    authenticate(("CommsLead",))
    body = validate_body([Field("cancel_reason", "string", required=True)])
    notice = L.get_notice(notice_id)
    if notice["state"] not in ("QUEUED", "BLOCKED"):
        fail("ERR_NOTICE_STATE_INVALID", "Only a QUEUED or BLOCKED notice may be cancelled.")
    incident = notice_incident(notice)
    L.require_not_frozen(incident)
    notice["state"] = "CANCELLED"
    notice["cancel_reason"] = body["cancel_reason"]
    touch(notice)
    L.refresh(incident)
    touch(incident)
    return ok(notice)
