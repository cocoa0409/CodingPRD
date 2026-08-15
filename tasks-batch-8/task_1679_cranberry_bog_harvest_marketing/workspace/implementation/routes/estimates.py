"""YieldEstimate endpoints: submit, get, list, approve/flag/revise transitions.

Approve/flag are FieldOfficer-only; revising a FLAGGED estimate back to
SUBMITTED belongs to the owning GrowerMember. Approval and flagging trigger
MemberQuota recomputation; the frost-damage cascade flips APPROVED -> FLAGGED.
"""
from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, forbidden, ANY_ROLE
from response import ok, created, paginate
from services import quota as quota_service
from validation import (get_body, req_string, req_number, req_enum, opt_number,
                        require_positive)

bp = Blueprint("estimates", __name__)

ESTIMATE_STATUSES = {"SUBMITTED", "APPROVED", "FLAGGED"}

# (from, to, grower_owner_allowed, field_officer_allowed)
ESTIMATE_TRANSITIONS = [
    ("SUBMITTED", "APPROVED", False, True),
    ("SUBMITTED", "FLAGGED", False, True),
    ("FLAGGED", "SUBMITTED", True, False),
]


def get_estimate_or_404(estimate_id):
    est = store.estimates.get(estimate_id)
    if est is None:
        raise ApiError("ERR_NOT_FOUND", 404, "YieldEstimate not found")
    return est


@bp.post("/coop/yield-estimates")
def create_estimate():
    body = get_body()
    bog_id = req_string(body, "bog_id")
    season_id = req_string(body, "season_id")
    estimated = require_positive(req_number(body, "estimated_barrels"), "estimated_barrels")

    uid, role = authenticate()
    require_roles(role, {"GrowerMember"})

    bog = store.bogs.get(bog_id)
    if bog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Bog not found")
    if bog["member_id"] != uid:
        forbidden("GrowerMember may only submit estimates for their own bogs")
    season = store.seasons.get(season_id)
    if season is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Season not found")

    for e in store.estimates.values():
        if e["bog_id"] == bog_id and e["season_id"] == season_id:
            raise ApiError("ERR_DUPLICATE_ESTIMATE", 409,
                           "A yield estimate already exists for this bog and season")

    if season["status"] not in ("SETUP", "OPEN"):
        raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                       "Season must be SETUP or OPEN for estimate submission")
    if bog["status"] != "ACTIVE":
        raise ApiError("ERR_BOG_NOT_ACTIVE", 409, "Bog is not ACTIVE")

    est = new_common({
        "bog_id": bog_id,
        "season_id": season_id,
        "member_id": bog["member_id"],
        "estimated_barrels": estimated,
        "revision_count": 0,
        "status": "SUBMITTED",
    })
    store.estimates[est["id"]] = est
    return created(est)


@bp.get("/coop/yield-estimates/<estimate_id>")
def get_estimate(estimate_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_estimate_or_404(estimate_id))


@bp.get("/coop/yield-estimates")
def list_estimates():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.estimates.values())
    rows = paginate.filter(rows, "bog_id")
    rows = paginate.filter(rows, "season_id")
    rows = paginate.filter(rows, "member_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/coop/yield-estimates/<estimate_id>/transition")
def transition_estimate(estimate_id):
    body = get_body()
    to = req_enum(body, "to", ESTIMATE_STATUSES)
    revised = opt_number(body, "revised_estimated_barrels")
    if revised is not None:
        require_positive(revised, "revised_estimated_barrels")

    uid, role = authenticate()
    require_roles(role, {"GrowerMember", "FieldOfficer"})

    # Band-3 transition-target role split (before existence).
    target_rows = [t for t in ESTIMATE_TRANSITIONS if t[1] == to]
    if target_rows:
        if role == "GrowerMember" and not any(t[2] for t in target_rows):
            forbidden("Transition to %s is FieldOfficer-only" % to)
        if role == "FieldOfficer" and not any(t[3] for t in target_rows):
            forbidden("Transition to %s is GrowerMember-only" % to)

    est = get_estimate_or_404(estimate_id)

    if role == "GrowerMember" and est["member_id"] != uid:
        forbidden("GrowerMember may only act on their own estimates")

    row = next((t for t in ESTIMATE_TRANSITIONS
                if t[0] == est["status"] and t[1] == to), None)
    if row is None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Estimate transition %s -> %s is not defined" % (est["status"], to))
    if role == "GrowerMember" and not row[2]:
        forbidden("Transition to %s is FieldOfficer-only" % to)
    if role == "FieldOfficer" and not row[3]:
        forbidden("Transition to %s is GrowerMember-only" % to)

    if to == "APPROVED":
        bog = store.bogs.get(est["bog_id"])
        if bog is None or bog["status"] != "ACTIVE":
            raise ApiError("ERR_BOG_NOT_ACTIVE", 409, "Bog is not ACTIVE")

    if to == "SUBMITTED":  # revise from FLAGGED
        if revised is not None:
            est["estimated_barrels"] = revised
        est["revision_count"] = est.get("revision_count", 0) + 1

    est["status"] = to
    touch(est)

    if to in ("APPROVED", "FLAGGED"):
        quota = quota_service.find_quota(est["member_id"], est["season_id"])
        if quota is not None:
            quota_service.recompute_quota(quota)

    return ok(est)
