"""Document production endpoints (privilege-gated)."""
from flask import Blueprint, g

import db
from lib import (
    ApiError,
    body_dict,
    forbidden,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    pagination_params,
    req_enum,
    req_str,
    require_role,
)
from services import production_view

bp = Blueprint("productions", __name__)


@bp.post("/litigation/engagements/<eid>/document-productions")
def create_production(eid):
    b = body_dict()
    title = req_str(b, "title")
    tier = req_enum(b, "privilege_tier", ("DISCOVERABLE", "WORK_PRODUCT", "PRIVILEGED"))
    content_ref = req_str(b, "content_ref")
    require_role("CaseManager")
    get_or_404(db.engagements, eid, "engagement")
    rec = db.base_record()
    rec.update(
        engagement_id=eid,
        title=title,
        privilege_tier=tier,
        content_ref=content_ref,
        status="REQUESTED",
    )
    db.productions[rec["id"]] = rec
    return ok(production_view(rec), 201)


@bp.get("/litigation/engagements/<eid>/document-productions")
def list_productions(eid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "Expert")
    eng = get_or_404(db.engagements, eid, "engagement")
    if g.user_role == "Expert" and eng["expert_id"] != g.user_id:
        forbidden("experts may access only their own engagements")
    recs = [p for p in db.productions.values() if p["engagement_id"] == eid]
    return list_ok([production_view(p) for p in recs], limit, offset)


@bp.post("/litigation/document-productions/<pid>/advance")
def advance_production(pid):
    b = body_dict()
    action = req_enum(b, "action", ("DELIVER", "ACKNOWLEDGE", "RECALL"))
    require_role("CaseManager", "Expert")
    # action-level role rules
    if action in ("DELIVER", "RECALL") and g.user_role != "CaseManager":
        forbidden("action %s requires CaseManager" % action)
    prod = get_or_404(db.productions, pid, "document production")
    eng = db.engagements[prod["engagement_id"]]
    if action == "ACKNOWLEDGE" and (
        g.user_role != "Expert" or eng["expert_id"] != g.user_id
    ):
        forbidden("only the engaged expert may acknowledge a production")
    if action == "DELIVER":
        if prod["status"] != "REQUESTED":
            invalid_state("only a REQUESTED production can be delivered")
        tier = prod["privilege_tier"]
        if tier == "DISCOVERABLE":
            gate = eng["status"] in ("SIGNED", "ACTIVE")
        elif tier == "WORK_PRODUCT":
            gate = eng["status"] == "ACTIVE"
        else:  # PRIVILEGED
            gate = eng["status"] == "ACTIVE" and eng["nda_executed"]
        if not gate:
            raise ApiError(
                "ERR_PRIVILEGE_TIER_BLOCKED",
                422,
                "privilege tier %s cannot be delivered while the engagement is %s"
                % (tier, eng["status"]),
            )
        prod["status"] = "DELIVERED"
    elif action == "ACKNOWLEDGE":
        if prod["status"] != "DELIVERED":
            invalid_state("only a DELIVERED production can be acknowledged")
        prod["status"] = "ACKNOWLEDGED"
    else:  # RECALL
        if prod["status"] != "DELIVERED":
            invalid_state("only a DELIVERED production can be recalled")
        prod["status"] = "RECALLED"
    db.touch(prod)
    return ok(production_view(prod))
