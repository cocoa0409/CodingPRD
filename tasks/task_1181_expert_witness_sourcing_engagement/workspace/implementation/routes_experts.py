"""Expert roster endpoints."""
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
    opt_int,
    pagination_params,
    req_enum,
    req_str,
    require_role,
)
from services import (
    active_engagement_count,
    check_view,
    evaluation_view,
    expert_view,
    fire_probation_cascade,
    review_view,
)

bp = Blueprint("experts", __name__)


@bp.post("/litigation/experts")
def create_expert():
    b = body_dict()
    full_name = req_str(b, "full_name")
    specialty = req_str(b, "specialty_area")
    dcc = opt_int(b, "daubert_challenge_count", 0, minimum=0)
    dec = opt_int(b, "daubert_exclusion_count", 0, minimum=0)
    mce = opt_int(b, "max_concurrent_engagements", 5, minimum=1)
    require_role("PlatformAdmin")
    rec = db.base_record()
    rec.update(
        full_name=full_name,
        specialty_area=specialty,
        roster_status="ACTIVE",
        daubert_challenge_count=dcc,
        daubert_exclusion_count=dec,
        max_concurrent_engagements=mce,
        rating_simple=0.0,
        rating_decayed=0.0,
    )
    db.experts[rec["id"]] = rec
    return ok(expert_view(rec), 201)


@bp.get("/litigation/experts")
def list_experts():
    limit, offset = pagination_params()
    require_role(
        "PlatformAdmin",
        "CaseManager",
        "ConflictAnalyst",
        "CredentialAnalyst",
        "BillingReviewer",
    )
    specialty = _opt_query("specialty_area")
    roster = _opt_query("roster_status")
    recs = list(db.experts.values())
    if specialty is not None:
        recs = [e for e in recs if e["specialty_area"] == specialty]
    if roster is not None:
        recs = [e for e in recs if e["roster_status"] == roster]
    return list_ok([expert_view(e) for e in recs], limit, offset)


def _opt_query(name):
    from flask import request as _req

    v = _req.args.get(name)
    return v if v is not None else None


@bp.get("/litigation/experts/<eid>")
def get_expert(eid):
    require_role(
        "PlatformAdmin",
        "CaseManager",
        "ConflictAnalyst",
        "CredentialAnalyst",
        "BillingReviewer",
        "Expert",
    )
    e = get_or_404(db.experts, eid, "expert")
    if g.user_role == "Expert" and g.user_id != e["id"]:
        forbidden("experts may read only their own record")
    return ok(expert_view(e))


@bp.post("/litigation/experts/<eid>/roster-status")
def roster_status(eid):
    b = body_dict()
    to_status = req_enum(b, "to_status", ("ACTIVE", "PROBATION", "REMOVED"))
    req_str(b, "rationale")
    require_role("PlatformAdmin")
    e = get_or_404(db.experts, eid, "expert")
    cur = e["roster_status"]
    allowed = {
        ("ACTIVE", "PROBATION"),
        ("PROBATION", "ACTIVE"),
        ("ACTIVE", "REMOVED"),
        ("PROBATION", "REMOVED"),
    }
    if (cur, to_status) not in allowed:
        invalid_state("roster status cannot transition %s -> %s" % (cur, to_status))
    if to_status == "REMOVED" and active_engagement_count(e["id"]) > 0:
        raise ApiError(
            "ERR_EXPERT_HAS_ACTIVE_ENGAGEMENTS",
            409,
            "expert has engagements in SIGNED or ACTIVE status",
        )
    e["roster_status"] = to_status
    db.touch(e)
    if to_status == "PROBATION":
        fire_probation_cascade(e)
    return ok(expert_view(e))


@bp.get("/litigation/experts/<eid>/conflict-checks")
def expert_conflict_checks(eid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "ConflictAnalyst")
    get_or_404(db.experts, eid, "expert")
    recs = [c for c in db.conflict_checks.values() if c["expert_id"] == eid]
    return list_ok([check_view(c) for c in recs], limit, offset)


@bp.get("/litigation/experts/<eid>/credential-reviews")
def expert_credential_reviews(eid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "CredentialAnalyst")
    get_or_404(db.experts, eid, "expert")
    recs = [r for r in db.credential_reviews.values() if r["expert_id"] == eid]
    return list_ok([review_view(r) for r in recs], limit, offset)


@bp.get("/litigation/experts/<eid>/evaluations")
def expert_evaluations(eid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "BillingReviewer")
    get_or_404(db.experts, eid, "expert")
    recs = [ev for ev in db.evaluations if ev["expert_id"] == eid]
    return list_ok([evaluation_view(ev) for ev in recs], limit, offset)
