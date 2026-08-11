"""Post-case evaluation endpoints."""
from flask import Blueprint

import db
from lib import (
    body_dict,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    opt_num_nullable,
    opt_str,
    pagination_params,
    req_num,
    require_role,
)
from services import (
    engagement_view,
    evaluation_view,
    evaluation_count,
    fire_probation_cascade,
    refresh_expert_ratings,
)

bp = Blueprint("evaluations", __name__)


@bp.post("/litigation/engagements/<eid>/evaluations")
def create_evaluation(eid):
    b = body_dict()
    overall = req_num(b, "overall_score", ge=0.0, le=5.0)
    quality = opt_num_nullable(b, "quality_score", ge=0.0, le=5.0)
    timeliness = opt_num_nullable(b, "timeliness_score", ge=0.0, le=5.0)
    testimony = opt_num_nullable(b, "testimony_score", ge=0.0, le=5.0)
    comments = opt_str(b, "comments", "")
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["status"] != "CLOSED":
        invalid_state("evaluations require a CLOSED engagement")
    rec = db.base_record()
    rec.pop("updated_at")  # evaluations are terminal: no updated_at / version
    rec.pop("version")
    rec.update(
        engagement_id=eid,
        expert_id=eng["expert_id"],
        overall_score=overall,
        quality_score=quality,
        timeliness_score=timeliness,
        testimony_score=testimony,
        comments=comments,
        evaluated_at=db.clock.now_raw(),
    )
    db.evaluations.append(rec)
    expert = db.experts[eng["expert_id"]]
    _simple, decayed = refresh_expert_ratings(expert)
    if (
        evaluation_count(expert["id"]) >= 2
        and decayed < 3.0
        and expert["roster_status"] == "ACTIVE"
    ):
        expert["roster_status"] = "PROBATION"
        db.touch(expert)
        fire_probation_cascade(expert)
    return ok(evaluation_view(rec), 201)


@bp.get("/litigation/engagements/<eid>/evaluations")
def list_evaluations(eid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "BillingReviewer")
    get_or_404(db.engagements, eid, "engagement")
    recs = [ev for ev in db.evaluations if ev["engagement_id"] == eid]
    return list_ok([evaluation_view(ev) for ev in recs], limit, offset)
