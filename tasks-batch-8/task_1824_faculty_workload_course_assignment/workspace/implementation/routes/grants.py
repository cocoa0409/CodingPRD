"""ReleaseTimeGrant endpoints (PRD §3.8): request, dean approve/deny with
buyout pricing, revoke with load-sheet compensation."""

import db
from errors import (
    ApiError,
    ERR_GRANT_NOT_FOUND,
    ERR_TERM_NOT_FOUND,
    ERR_FACULTY_NOT_FOUND,
    ERR_VALIDATION,
    ERR_RELEASE_PERIOD_OVERLAP,
    ERR_INVALID_GRANT_TRANSITION,
)
from middleware import authenticate, require_to_state_role, ALL_ROLES, CHAIR, DEAN
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, parse_date, dec
import services

bp = make_blueprint("grants")

GRANT_TYPES = ["RESEARCH_BUYOUT", "ADMINISTRATIVE", "SABBATICAL"]
GRANT_STATUSES = ["REQUESTED", "APPROVED", "DENIED", "REVOKED"]

TO_STATE_ROLES = {
    "APPROVED": {DEAN},
    "DENIED": {DEAN},
    "REVOKED": {CHAIR, DEAN},
}


def require_grant(grant_id):
    grant = db.get("release_time_grants", grant_id)
    if grant is None:
        raise ApiError(ERR_GRANT_NOT_FOUND, 404, "release-time grant not found")
    return grant


@bp.post("/release-time-grants")
def create_grant():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "term_id": {"type": "string", "required": True},
        "faculty_id": {"type": "string", "required": True},
        "grant_type": {"type": "enum", "values": GRANT_TYPES, "required": True},
        "credits_released": {"type": "number", "min": 0, "min_exclusive": True, "required": True},
        "start_date": {"type": "date", "required": True},
        "end_date": {"type": "date", "required": True},
    })
    start = parse_date(body["start_date"], "start_date")
    end = parse_date(body["end_date"], "end_date")
    if end < start:
        raise ApiError(ERR_VALIDATION, 400, "end_date must not precede start_date")
    # Existence (priority 4), body FKs in declared input order.
    term = db.get("workload_terms", body["term_id"])
    if term is None:
        raise ApiError(ERR_TERM_NOT_FOUND, 404, "term not found")
    faculty = db.get("faculty_members", body["faculty_id"])
    if faculty is None:
        raise ApiError(ERR_FACULTY_NOT_FOUND, 404, "faculty member not found")
    # Shape-level range: credits_released may not exceed the contractual load.
    if dec(body["credits_released"]) > dec(faculty["base_load_credits"]):
        raise ApiError(ERR_VALIDATION, 400,
                       "credits_released must not exceed the faculty member's base_load_credits")
    # Temporal (priority 7): CLOSED-interval overlap against REQUESTED/APPROVED
    # grants of the same (faculty, term) — sharing a single day conflicts.
    for other in db.all_of("release_time_grants"):
        if (other["faculty_id"] == faculty["id"] and other["term_id"] == term["id"]
                and other["status"] in ("REQUESTED", "APPROVED")):
            other_start = parse_date(other["start_date"], "start_date")
            other_end = parse_date(other["end_date"], "end_date")
            if start <= other_end and other_start <= end:
                raise ApiError(ERR_RELEASE_PERIOD_OVERLAP, 409,
                               "release period overlaps another REQUESTED or APPROVED grant")
    grant = db.new_entity("release_time_grants", {
        "term_id": term["id"],
        "faculty_id": faculty["id"],
        "grant_type": body["grant_type"],
        "credits_released": body["credits_released"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "buyout_value_cents": None,
        "status": "REQUESTED",
    })
    # A grant auto-creates the pair's load sheet if none exists yet.
    services.get_or_create_sheet(term["id"], faculty["id"])
    return success_obj(db.public(grant), 201)


@bp.get("/release-time-grants")
def list_grants():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("release_time_grants"), ["term_id", "faculty_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(g) for g in page], limit, offset, total, has_more)


@bp.get("/release-time-grants/<grantId>")
def get_grant(grantId):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_grant(grantId)), 200)


@bp.post("/release-time-grants/<grantId>/transition")
def transition_grant(grantId):
    user_id, role = authenticate([CHAIR, DEAN])
    body = body_json()
    check_shape(body, {"to_state": {"type": "enum", "values": GRANT_STATUSES, "required": True}})
    to_state = body["to_state"]
    require_to_state_role(role, to_state, TO_STATE_ROLES)
    grant = require_grant(grantId)
    from_state = grant["status"]
    if to_state == "APPROVED":
        if from_state != "REQUESTED":
            raise ApiError(ERR_INVALID_GRANT_TRANSITION, 409,
                           f"cannot move a {from_state} grant to APPROVED")
        faculty = db.get("faculty_members", grant["faculty_id"])
        term = db.get("workload_terms", grant["term_id"])
        # Price the buyout: SALARY_PRORATE for RESEARCH_BUYOUT, FLAT_RATE else.
        grant["buyout_value_cents"] = services.buyout_value_cents(grant, faculty, term)
        grant["status"] = "APPROVED"
        db.touch(grant)
        sheet = services.get_or_create_sheet(grant["term_id"], grant["faculty_id"])
        services.recompute_sheet(sheet)
        return success_obj(db.public(grant), 200)
    if to_state == "DENIED":
        if from_state != "REQUESTED":
            raise ApiError(ERR_INVALID_GRANT_TRANSITION, 409,
                           f"cannot move a {from_state} grant to DENIED")
        grant["status"] = "DENIED"
        db.touch(grant)
        return success_obj(db.public(grant), 200)
    # REVOKED (chair or dean, from APPROVED).
    if from_state != "APPROVED":
        raise ApiError(ERR_INVALID_GRANT_TRANSITION, 409,
                       f"cannot move a {from_state} grant to REVOKED")
    grant["status"] = "REVOKED"
    db.touch(grant)
    # The release credit is returned; buyout_value_cents stays for audit.
    services.recompute_pair(grant["term_id"], grant["faculty_id"])
    return success_obj(db.public(grant), 200)
