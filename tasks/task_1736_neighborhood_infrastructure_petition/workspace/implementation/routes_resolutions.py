"""CouncilResolution endpoint (§3.5) — protest-weighted council vote."""
from datetime import timedelta

from flask import Blueprint

import errors
import services
import shape
from envelope import ok_object
from helpers import get_or_404
from security import STAFF_ROLES, authenticate, require_role
from serializers import ser_resolution
from store import STORE, new_id, now, touch

bp = Blueprint("resolutions", __name__)

SUPERMAJORITY_TRIGGER = 50.00
SIMPLE_MAJORITY = 3
SUPERMAJORITY = 4
MAX_REMANDS = 2


@bp.route("/resolutions", methods=["POST"])
def create_resolution():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    expected_version = shape.req_int(body, "expected_district_version")
    motion = shape.req_enum(body, "motion", {"APPROVE", "REJECT", "REMAND"})
    votes_for = shape.req_int(body, "votes_for")
    votes_against = shape.req_int(body, "votes_against")
    if not (0 <= votes_for <= 5) or not (0 <= votes_against <= 5) \
            or votes_for + votes_against > 5:
        errors.raise_err(errors.INVALID_REQUEST,
                         "votes_for and votes_against must each be 0..5 and sum to at most 5")
    ctx = authenticate()
    require_role(ctx, ["CouncilPresident"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    if expected_version != d["version"]:
        errors.raise_err(errors.STALE_VERSION,
                         "expected_district_version does not match the district's current version")
    if d["status"] != "COUNCIL_REVIEW":
        errors.raise_err(errors.DISTRICT_NOT_IN_COUNCIL_REVIEW,
                         "District must be in COUNCIL_REVIEW")
    if motion == "REMAND" and d["remand_count"] >= MAX_REMANDS:
        errors.raise_err(errors.REMAND_LIMIT_EXCEEDED,
                         "The district has already been remanded twice")

    protest = d["protest_frontage_pct"]
    required = SUPERMAJORITY if (protest is not None and protest >= SUPERMAJORITY_TRIGGER) \
        else SIMPLE_MAJORITY
    if motion == "APPROVE":
        outcome = "ADOPTED" if votes_for >= required else "FAILED"
    else:  # REJECT / REMAND use the simple majority
        outcome = "ADOPTED" if votes_for >= SIMPLE_MAJORITY else "FAILED"

    ts = now()
    r = {
        "id": new_id(),
        "district_id": district_id,
        "motion": motion,
        "votes_for": votes_for,
        "votes_against": votes_against,
        "outcome": outcome,
        "protest_pct_snapshot": protest,
        "required_votes_snapshot": required,
        "recorded_by": ctx.user_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("resolutions", r)

    if motion == "APPROVE" and outcome == "ADOPTED":
        # levy the roll
        d["status"] = "APPROVED"
        d["levy_date"] = ts
        d["payment_option_deadline"] = ts + timedelta(days=30)
        for a in STORE.assessments.values():
            if a["district_id"] == district_id and a["status"] == "PRELIMINARY":
                a["status"] = "LEVIED"
                a["principal_balance_cents"] = a["preliminary_amount_cents"]
                touch(a)
    elif (motion == "APPROVE" and outcome == "FAILED") or \
            (motion == "REJECT" and outcome == "ADOPTED"):
        # abandoned: hearing voided, preliminary assessments superseded
        d["status"] = "ABANDONED"
        for h in STORE.hearings.values():
            if h["district_id"] == district_id and h["status"] == "CLOSED":
                h["status"] = "VOIDED"
                touch(h)
        services.supersede_preliminary_assessments(d)
    elif motion == "REMAND" and outcome == "ADOPTED":
        d["remand_count"] += 1
        d["status"] = "SCOPING"
        for h in STORE.hearings.values():
            if h["district_id"] == district_id and h["status"] == "CLOSED":
                h["status"] = "SUPERSEDED"
                touch(h)
        services.supersede_preliminary_assessments(d)
        for e in STORE.estimates.values():
            if e["district_id"] == district_id and e["status"] in ("SUBMITTED", "APPROVED"):
                e["status"] = "SUPERSEDED"
                touch(e)
        d["approved_estimate_id"] = None
    # FAILED REJECT / FAILED REMAND: district stays in COUNCIL_REVIEW
    touch(d)
    return ok_object(ser_resolution(r), 201)


@bp.route("/resolutions/<rid>", methods=["GET"])
def get_resolution(rid):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    r = get_or_404("resolutions", rid, errors.RESOLUTION_NOT_FOUND,
                   "Resolution not found")
    return ok_object(ser_resolution(r))
