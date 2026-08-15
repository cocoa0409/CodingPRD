"""Stateless site-match scoring (PRD §3.2): persists nothing."""
from flask import Blueprint

from db import store
from middleware import authenticate, body, require_fields, get_fk
from response import success_object
from services import calc

bp = Blueprint("match", __name__)


@bp.post("/api/match-evaluations")
def match_evaluation():
    authenticate(["TenantRep", "LeasingManager"])
    b = body()
    # Priority 4 (existence) precedes priority 5 (shape) for present string ids.
    req = get_fk(b, "requirement_id", store.requirements)
    site = get_fk(b, "site_id", store.sites)
    require_fields(b, [
        ("requirement_id", "string", True),
        ("site_id", "string", True),
    ])
    if req is None:
        req = store.requirements[b["requirement_id"]]
    if site is None:
        site = store.sites[b["site_id"]]
    score, hard = calc.match_evaluation(site, req)
    return success_object({
        "requirement_id": req["id"],
        "site_id": site["id"],
        "match_score": float(score),
        "hard_minimums_met": hard,
    })
