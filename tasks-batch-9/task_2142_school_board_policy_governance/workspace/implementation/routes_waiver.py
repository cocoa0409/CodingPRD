"""Policy waiver requests: filing, committee review and revocation."""

from flask import Blueprint

import auth
import calc
import resp
import store
import validate as v
from errors import fail
from store import db, set_fields

bp = Blueprint("waiver", __name__)

WAIVER_STATUSES = ["SUBMITTED", "BOARD_PENDING", "GRANTED", "DENIED", "EXPIRED",
                   "REVOKED"]
RECOMMENDATIONS = ["RECOMMEND_GRANT", "RECOMMEND_DENY"]
LIVE_STATUSES = ("SUBMITTED", "BOARD_PENDING", "GRANTED")


@bp.post("/governance/waiver-requests")
def create_waiver():
    auth.authorize(["SchoolPrincipal"])
    body = v.body()
    policy_id = v.req_id(body, "policy_id")
    committee_id = v.req_id(body, "reviewing_committee_id")
    school_code = v.req_str(body, "requesting_school_code")
    justification = v.req_str(body, "justification")
    start = v.req_dt(body, "requested_start_date")
    end = v.req_dt(body, "requested_end_date")
    if end <= start:
        fail("ERR_INVALID_REQUEST",
             "requested_end_date must be strictly after requested_start_date.")

    policy = v.find("policies", policy_id)
    v.find("committees", committee_id)

    for other in db["waivers"].values():
        if other["status"] not in LIVE_STATUSES:
            continue
        if other["policy_id"] != policy_id:
            continue
        if other["requesting_school_code"] != school_code:
            continue
        if other["requested_start_date"] < end \
                and start < other["requested_end_date"]:
            fail("ERR_WAIVER_WINDOW_OVERLAP",
                 "A live waiver already covers part of the requested window.")

    requested_days = store.days_between(start, end)
    if requested_days < 1:
        fail("ERR_INVALID_WAIVER_WINDOW",
             "The requested window is shorter than one whole day.")
    max_allowed = calc.WAIVER_MAX_DAYS[policy["legal_requirement_level"]]
    if requested_days > max_allowed:
        fail("ERR_WAIVER_DURATION_EXCEEDS_CAP",
             "The requested window exceeds the cap of %d days." % max_allowed)

    rec = store.create("waivers", "WaiverRequest", {
        "policy_id": policy_id,
        "reviewing_committee_id": committee_id,
        "requesting_school_code": school_code,
        "justification": justification,
        "requested_start_date": start,
        "requested_end_date": end,
        "status": "SUBMITTED",
        "committee_recommendation": None,
        "denial_stage": None,
        "max_allowed_days": max_allowed,
        "granted_start_date": None,
        "granted_end_date": None,
        "granted_days": 0,
        "revoked_on": None,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/waiver-requests")
def list_waivers():
    auth.authorize(auth.READ_ROLES_PUBLIC)
    limit, offset = v.pagination()
    policy_id = v.query_str("policy_id")
    committee_id = v.query_str("reviewing_committee_id")
    status = v.query_enum("status", WAIVER_STATUSES)
    school_code = v.query_str("requesting_school_code")
    items = store.sorted_rows("waivers")
    if policy_id is not None:
        items = [w for w in items if w["policy_id"] == policy_id]
    if committee_id is not None:
        items = [w for w in items if w["reviewing_committee_id"] == committee_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if school_code is not None:
        items = [w for w in items if w["requesting_school_code"] == school_code]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(w) for w in page], limit, offset, total)


@bp.get("/governance/waiver-requests/<waiver_id>")
def get_waiver(waiver_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("waivers", waiver_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/waiver-requests/<waiver_id>/committee-recommendation")
def committee_recommendation(waiver_id):
    user_id, role = auth.authorize(["BoardMember"])
    waiver = v.find("waivers", waiver_id)
    body = v.body()
    recommendation = v.req_enum(body, "recommendation", RECOMMENDATIONS)

    is_chair = False
    for a in db["assignments"].values():
        if a["committee_id"] == waiver["reviewing_committee_id"] \
                and a["board_member_id"] == user_id \
                and a["status"] == "ACTIVE" \
                and a["role_on_committee"] == "CHAIR":
            is_chair = True
            break
    if not is_chair:
        fail("ERR_IDENTITY_MISMATCH",
             "Only the active chair of the reviewing committee may record it.")

    if waiver["status"] != "SUBMITTED":
        fail("ERR_WAIVER_NOT_IN_REVIEW",
             "The waiver is not awaiting a committee recommendation.")

    committee = db["committees"].get(waiver["reviewing_committee_id"])
    if committee is None or committee["status"] != "ACTIVE":
        fail("ERR_COMMITTEE_INQUORATE",
             "The reviewing committee is inquorate.")

    if recommendation == "RECOMMEND_GRANT":
        set_fields(waiver, committee_recommendation=recommendation,
                   status="BOARD_PENDING")
    else:
        set_fields(waiver, committee_recommendation=recommendation,
                   status="DENIED", denial_stage="COMMITTEE")
        calc.withdraw_items_for_waiver(waiver)
    return resp.ok(store.serialize(waiver))


@bp.post("/governance/waiver-requests/<waiver_id>/revoke")
def revoke_waiver(waiver_id):
    user_id, role = auth.authorize(["Superintendent", "BoardPresident"])
    waiver = v.find("waivers", waiver_id)
    auth.enforce_president(user_id, role)

    if waiver["status"] != "GRANTED":
        fail("ERR_WAIVER_NOT_IN_REVIEW", "Only a granted waiver may be revoked.")

    now = store.now()
    days = store.days_between(waiver["granted_start_date"], now)
    if days < 0:
        days = 0
    set_fields(waiver, status="REVOKED", revoked_on=now, granted_end_date=now,
               granted_days=days)

    policy = db["policies"].get(waiver["policy_id"])
    if policy is not None:
        calc.policy_scoped_recompute(policy)
    calc.withdraw_items_for_waiver(waiver)
    return resp.ok(store.serialize(waiver))
