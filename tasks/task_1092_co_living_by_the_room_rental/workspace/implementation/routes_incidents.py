"""Routes: house-rule incidents, adjudication (with compliance cascade), disputes."""
from datetime import timedelta

from flask import Blueprint, g

import helpers as h
import domain as d
import routes_memberships as rm
from state import S, clock_date

bp = Blueprint("incidents", __name__)

_RULES = {"QUIET_HOURS", "GUEST_POLICY", "CLEANLINESS", "SMOKING", "UNAUTHORIZED_OCCUPANT"}
_SEV = {"MINOR", "MAJOR", "SEVERE"}


@bp.post("/co-living/incidents")
def create_incident():
    h.authorize("CommunityManager", "ComplianceOfficer", "Member")
    b = h.body()
    # Priority 4: ownership for Member
    if g.role == "Member":
        mid = b.get("membership_id")
        mem = S.memberships.get(mid) if isinstance(mid, str) else None
        if mem is None or mem["member_id"] != g.user_id:
            raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the tenancy")
    # Priority 5: shape
    membership_id = h.req_str(b, "membership_id")
    rule_code = h.req_enum(b, "rule_code", _RULES)
    severity = h.req_enum(b, "severity", _SEV)
    description = h.req_str(b, "description")
    occurred_at = h.req_instant(b, "occurred_at")
    # Priority 6: FK
    mem = h.find_or_404(S.memberships, membership_id, "ERR_MEMBERSHIP_NOT_FOUND")

    incident = h.new_common()
    incident.update({
        "house_id": mem["house_id"],
        "membership_id": membership_id,
        "rule_code": rule_code,
        "severity": severity,
        "severity_points": d.SEVERITY_POINTS[severity],
        "occurred_at": b["occurred_at"],
        "description": description,
        "status": "REPORTED",
        "reported_by_user_id": g.user_id,
        "adjudicated_by_user_id": None,
        "dispute_round": 0,
        "dispute_reason": None,
        "_occurred_dt": occurred_at,
    })
    S.incidents[incident["id"]] = incident
    return h.ok(d.serialize(incident), 201)


@bp.get("/co-living/incidents/<iid>")
def get_incident(iid):
    h.authorize(*h.ROLES)
    inc = h.find_or_404(S.incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    return h.ok(d.serialize(inc), 200)


@bp.get("/co-living/incidents")
def list_incidents():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    house_id = h.query_val("house_id")
    membership_id = h.query_val("membership_id")
    status = h.query_val("status")
    rows = []
    for inc in S.incidents.values():
        if house_id is not None and inc["house_id"] != house_id:
            continue
        if membership_id is not None and inc["membership_id"] != membership_id:
            continue
        if status is not None and inc["status"] != status:
            continue
        rows.append(inc)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


def _member_of(incident):
    mem = S.memberships.get(incident["membership_id"])
    if mem is None:
        return None
    return S.members.get(mem["member_id"])


def _compliance_cascade(member):
    """Hops 2-4: any ACTIVE tenancy of the member -> NOTICE_GIVEN(COMPLIANCE)."""
    for mem in S.memberships.values():
        if mem["member_id"] == member["id"] and mem["tenancy_status"] == "ACTIVE":
            sched = clock_date() + timedelta(days=d.COMPLIANCE_NOTICE_DAYS)
            rm._apply_notice(mem, "COMPLIANCE", sched, h.fmt_date(sched))


@bp.post("/co-living/incidents/<iid>/adjudicate")
def adjudicate_incident(iid):
    h.authorize("ComplianceOfficer")
    inc = h.find_or_404(S.incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    b = h.body()
    outcome = h.req_enum(b, "outcome", {"UPHOLD", "DISMISS"})
    note = h.opt_str(b, "adjudication_note")
    # Priority 10: state
    if inc["status"] not in ("REPORTED", "DISPUTED"):
        raise h.ApiError("ERR_INVALID_INCIDENT_STATE", "incident not REPORTED/DISPUTED")
    # Priority 17: segregation of duties
    if g.user_id == inc["reported_by_user_id"]:
        raise h.ApiError("ERR_SEGREGATION_OF_DUTIES", "adjudicator equals reporter")

    inc["adjudicated_by_user_id"] = g.user_id
    if outcome == "DISMISS":
        inc["status"] = "DISMISSED"
    else:
        inc["status"] = "UPHELD"
    h.touch(inc)

    member = _member_of(inc)
    if member is not None:
        d.recompute_member_standing(member)
        if outcome == "UPHOLD" and member["strike_points"] >= d.STRIKE_SUSPENSION_THRESHOLD:
            _compliance_cascade(member)
    return h.ok(d.serialize(inc), 200)


@bp.post("/co-living/incidents/<iid>/dispute")
def dispute_incident(iid):
    h.authorize("Member")
    inc = h.find_or_404(S.incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    # Priority 4: ownership
    mem = S.memberships.get(inc["membership_id"])
    if mem is None or mem["member_id"] != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the tenancy")
    b = h.body()
    reason = h.req_field(b, "dispute_reason")
    if not isinstance(reason, str):
        raise h.ApiError("ERR_INVALID_REQUEST", "dispute_reason must be a string")
    # Priority 10: state
    if inc["status"] != "UPHELD":
        raise h.ApiError("ERR_INVALID_INCIDENT_STATE", "incident is not UPHELD")
    # Priority 28: dispute limit
    if inc["dispute_round"] >= d.MAX_DISPUTE_ROUNDS:
        raise h.ApiError("ERR_DISPUTE_LIMIT_REACHED", "dispute limit reached")

    inc["status"] = "DISPUTED"
    inc["dispute_round"] += 1
    inc["dispute_reason"] = reason
    h.touch(inc)
    member = _member_of(inc)
    if member is not None:
        d.recompute_member_standing(member)
    return h.ok(d.serialize(inc), 200)
