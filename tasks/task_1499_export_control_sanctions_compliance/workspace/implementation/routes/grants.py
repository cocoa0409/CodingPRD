"""Foreign-national access grant endpoints: request, review, activate, revoke."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_FOREIGN_NATIONAL_REQUIRED,
    ERR_GRANT_PERIOD_OVERLAP,
    ERR_GRANT_WINDOW_INVALID,
    ERR_INVALID_STATE,
    ERR_PARTY_BLOCKED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TCP_INACTIVE,
    ERR_VALIDATION,
)
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_str,
    v_enum,
    v_date,
    find,
    check_body_fks,
    page_params,
    filtered_sorted,
)
from response import ok, list_response
from services.audit import write_audit

bp = Blueprint("grants", __name__)


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: adjacent windows (end == start) do NOT
    conflict."""
    return a_start < b_end and b_start < a_end


def _has_conflicting_grant(grant):
    for other in db.GRANTS.values():
        if (
            other["id"] != grant["id"]
            and other["party_id"] == grant["party_id"]
            and other["tcp_id"] == grant["tcp_id"]
            and other["status"] in ("APPROVED", "ACTIVE")
            and _half_open_overlap(
                grant["start_date"], grant["end_date"],
                other["start_date"], other["end_date"],
            )
        ):
            return True
    return False


@bp.post("/compliance/access-grants")
def create_grant():
    uid, _ = auth("ComplianceAnalyst")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("tcp_id", db.TCPS), ("party_id", db.PARTIES)))
    # Priority 4: request shape
    no_unknown(body, {"tcp_id", "party_id", "start_date", "end_date"})
    tcp_id = v_str(need(body, "tcp_id"), "tcp_id")
    party_id = v_str(need(body, "party_id"), "party_id")
    start_date = v_date(need(body, "start_date"), "start_date")
    end_date = v_date(need(body, "end_date"), "end_date")
    if not start_date < end_date:
        raise ApiError(ERR_VALIDATION, "start_date must be strictly before end_date", 400)
    find(db.TCPS, tcp_id, "TechnologyControlPlan")
    party = find(db.PARTIES, party_id, "Party")
    # Priority 7: sanctions safety
    if party["screening_posture"] == "BLOCKED":
        raise ApiError(ERR_PARTY_BLOCKED, "Party %s is BLOCKED" % party["id"], 409)
    # Priority 9: foreign-national eligibility
    if not party["is_foreign_national"]:
        raise ApiError(
            ERR_FOREIGN_NATIONAL_REQUIRED,
            "Party %s is not a foreign national" % party["id"],
            409,
        )
    grant = {
        "tcp_id": tcp_id,
        "party_id": party_id,
        "start_date": start_date,
        "end_date": end_date,
        "requested_by_user_id": uid,
        "reviewed_by_user_id": None,
        "status": "REQUESTED",
    }
    db.stamp_new(grant)
    db.GRANTS[grant["id"]] = grant
    return ok(db.pub(grant), "object", 201)


@bp.get("/compliance/access-grants/<gid>")
def get_grant(gid):
    auth()
    grant = find(db.GRANTS, gid, "AccessGrant")
    return ok(db.pub(grant), "object", 200)


@bp.get("/compliance/access-grants")
def list_grants():
    auth()
    filters = {
        "tcp_id": request.args.get("tcp_id"),
        "party_id": request.args.get("party_id"),
        "status": request.args.get("status"),
    }
    items = filtered_sorted(db.GRANTS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/access-grants/<gid>/review")
def review_grant(gid):
    uid, _ = auth("ComplianceManager")
    grant = find(db.GRANTS, gid, "AccessGrant")
    body = get_body()
    no_unknown(body, {"decision"})
    decision = v_enum(need(body, "decision"), "decision", ("APPROVE", "DENY"))
    if grant["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "AccessGrant is not REQUESTED", 409)
    if uid == grant["requested_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the requester", 409
        )
    if decision == "APPROVE":
        if _has_conflicting_grant(grant):
            raise ApiError(
                ERR_GRANT_PERIOD_OVERLAP,
                "Another APPROVED|ACTIVE grant overlaps this party and plan",
                409,
            )
        grant["status"] = "APPROVED"
    else:  # DENY
        grant["status"] = "DENIED"
    grant["reviewed_by_user_id"] = uid
    db.touch(grant)
    return ok(db.pub(grant), "object", 200)


@bp.post("/compliance/access-grants/<gid>/activate")
def activate_grant(gid):
    uid, role = auth("ComplianceManager")
    grant = find(db.GRANTS, gid, "AccessGrant")
    # Priority 6: from-state
    if grant["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "AccessGrant is not APPROVED", 409)
    # Priority 7: sanctions safety
    party = find(db.PARTIES, grant["party_id"], "Party")
    if party["screening_posture"] == "BLOCKED":
        raise ApiError(ERR_PARTY_BLOCKED, "Party %s is BLOCKED" % party["id"], 409)
    # Priority 8: structural compliance
    tcp = find(db.TCPS, grant["tcp_id"], "TechnologyControlPlan")
    if tcp["status"] != "ACTIVE":
        raise ApiError(ERR_TCP_INACTIVE, "TechnologyControlPlan is not ACTIVE", 409)
    today = db.today()
    if not (grant["start_date"] <= today < grant["end_date"]):
        raise ApiError(
            ERR_GRANT_WINDOW_INVALID,
            "Current date is outside the grant window [start_date, end_date)",
            409,
        )
    if _has_conflicting_grant(grant):
        raise ApiError(
            ERR_GRANT_PERIOD_OVERLAP,
            "Another APPROVED|ACTIVE grant overlaps this party and plan",
            409,
        )
    grant["status"] = "ACTIVE"
    db.touch(grant)
    party["active_grant_count"] += 1
    db.touch(party)
    write_audit(
        "GRANT_ACTIVATED", "AccessGrant", grant["id"], role, uid,
        "AccessGrant %s activated" % grant["id"],
    )
    return ok(db.pub(grant), "object", 200)


@bp.post("/compliance/access-grants/<gid>/revoke")
def revoke_grant(gid):
    uid, role = auth("ComplianceManager")
    grant = find(db.GRANTS, gid, "AccessGrant")
    if grant["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "AccessGrant is not ACTIVE", 409)
    grant["status"] = "REVOKED"
    db.touch(grant)
    party = find(db.PARTIES, grant["party_id"], "Party")
    party["active_grant_count"] -= 1
    db.touch(party)
    write_audit(
        "GRANT_REVOKED", "AccessGrant", grant["id"], role, uid,
        "AccessGrant %s revoked" % grant["id"],
    )
    return ok(db.pub(grant), "object", 200)
