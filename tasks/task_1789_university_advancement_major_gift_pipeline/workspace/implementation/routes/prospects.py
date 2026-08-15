"""Prospects, moves management, research assessments, recognition read."""

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, opt_str,
    req_int, req_money, req_enum, now, new_entity, touch,
    success_object, success_list, paginate, ALL_ROLES,
)
from db import store
from errors import (
    fail, ERR_PROSPECT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_MOVES_TRANSITION, ERR_PROSPECT_NOT_RATED,
    ERR_SEGREGATION_OF_DUTIES, ERR_ASSESSMENT_NOT_REVIEWABLE,
)
from services import (
    ser_prospect, ser_assignment, ser_assessment, ser_credit_split,
    capacity_affinity_rating, recognition_read, refresh_prospect_recognition,
    require_prospect_owner, bump_owner_fundraiser,
)

bp = Blueprint("prospects", __name__)


def _get_prospect(pid):
    prospect = store["prospects"].get(pid)
    if prospect is None:
        fail(ERR_PROSPECT_NOT_FOUND, "Prospect not found")
    return prospect


@bp.post("/advancement/prospects")
def create_prospect():
    user_id, role = authenticate()
    authorize(role, ["ProspectResearcher"])
    body = body_json()
    check_unknown_fields(body, {"full_name", "prospect_type", "contact_email", "spouse_prospect_id"})
    full_name = req_str(body, "full_name")
    prospect_type = req_enum(body, "prospect_type", {"INDIVIDUAL", "ORGANIZATION"})
    contact_email = req_str(body, "contact_email")
    spouse_prospect_id = opt_str(body, "spouse_prospect_id")
    if spouse_prospect_id is not None and spouse_prospect_id not in store["prospects"]:
        fail(ERR_PROSPECT_NOT_FOUND, "spouse_prospect_id does not resolve to a prospect")
    entity = new_entity()
    entity.update({
        "full_name": full_name,
        "prospect_type": prospect_type,
        "contact_email": contact_email,
        "spouse_prospect_id": spouse_prospect_id,
        "research_status": "IDENTIFIED",
        "moves_stage": "QUALIFICATION",
        "capacity_band": None,
        "affinity_score": None,
        "rated_assessment_id": None,
        "rated_adjusted_capacity_cents": None,
        "recognition_society_id": None,
    })
    store["prospects"][entity["id"]] = entity
    return success_object(ser_prospect(entity), 201)


@bp.get("/advancement/prospects/<pid>")
def get_prospect(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_prospect(_get_prospect(pid)))


@bp.get("/advancement/prospects")
def list_prospects():
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    items = all_prospects = list(store["prospects"].values())
    for param in ("research_status", "moves_stage", "capacity_band", "spouse_prospect_id",
                  "rated_assessment_id", "recognition_society_id"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    page, limit, offset, total = paginate(items)
    return success_list([ser_prospect(p) for p in page], limit, offset, total)


@bp.post("/advancement/prospects/<pid>/disqualify")
def disqualify_prospect(pid):
    user_id, role = authenticate()
    authorize(role, ["ProspectResearcher", "AdvancementDirector"])
    body_json()  # no documented inputs
    prospect = _get_prospect(pid)
    if prospect["research_status"] == "DISQUALIFIED":
        fail(ERR_INVALID_MOVES_TRANSITION, "Prospect is already DISQUALIFIED")
    prospect["research_status"] = "DISQUALIFIED"
    touch(prospect)
    touched_fundraisers = set()
    # release every ACTIVE assignment with released_reason DISQUALIFIED
    for a in store["assignments"].values():
        if a["prospect_id"] == pid and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            a["released_reason"] = "DISQUALIFIED"
            touch(a)
            touched_fundraisers.add(a["fundraiser_id"])
    # reject every open-pipeline proposal
    for p in store["proposals"].values():
        if p["prospect_id"] == pid and p["status"] in ("DRAFT", "UNDER_REVIEW", "NEGOTIATING", "RETURNED"):
            p["status"] = "REJECTED"
            p["decision_rationale"] = "PROSPECT_DISQUALIFIED"
            touch(p)
    for fid in touched_fundraisers:
        fundraiser = store["fundraisers"].get(fid)
        if fundraiser is not None:
            touch(fundraiser)
    return success_object(ser_prospect(prospect))


# Legal direct-API moves: target_stage -> set of source stages.
_MOVES = {
    "QUALIFICATION": {"CULTIVATION"},
    "CULTIVATION": {"QUALIFICATION", "SOLICITATION", "NEGOTIATION", "STEWARDSHIP"},
    "SOLICITATION": {"CULTIVATION"},
    "NEGOTIATION": {"SOLICITATION"},
    "CLOSED_LOST": {"QUALIFICATION", "CULTIVATION", "SOLICITATION", "NEGOTIATION", "STEWARDSHIP"},
}


@bp.post("/advancement/prospects/<pid>/moves")
def move_prospect(pid):
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body = body_json()
    check_unknown_fields(body, {"target_stage", "note"})
    target = req_enum(body, "target_stage",
                      {"QUALIFICATION", "CULTIVATION", "SOLICITATION", "NEGOTIATION", "STEWARDSHIP", "CLOSED_LOST"})
    opt_str(body, "note")
    prospect = _get_prospect(pid)
    # portfolio ownership (priority 5)
    require_prospect_owner(user_id, pid)
    current = prospect["moves_stage"]
    if target == "STEWARDSHIP":
        # system-reserved stage; direct moves never allowed
        fail(ERR_INVALID_MOVES_TRANSITION, "STEWARDSHIP is reached only via agreement execution")
    if current == "CLOSED_LOST":
        fail(ERR_INVALID_MOVES_TRANSITION, "Prospect is CLOSED_LOST")
    if target not in _MOVES or current not in _MOVES.get(target, set()):
        fail(ERR_INVALID_MOVES_TRANSITION, f"Move from {current} to {target} is not allowed")
    if current == "QUALIFICATION" and target == "CULTIVATION":
        if prospect["research_status"] == "DISQUALIFIED":
            fail(ERR_INVALID_MOVES_TRANSITION, "Disqualified prospect cannot enter CULTIVATION")
    if target == "SOLICITATION":
        if prospect["research_status"] != "RATED":
            fail(ERR_PROSPECT_NOT_RATED, "Prospect must be RATED to enter SOLICITATION")
    if target == "NEGOTIATION":
        has_approved = any(
            p["prospect_id"] == pid and p["status"] == "APPROVED"
            for p in store["proposals"].values()
        )
        if not has_approved:
            fail(ERR_INVALID_MOVES_TRANSITION, "Entering NEGOTIATION requires an APPROVED proposal")
    prospect["moves_stage"] = target
    touch(prospect)
    return success_object(ser_prospect(prospect))


@bp.get("/advancement/prospects/<pid>/assignments")
def list_prospect_assignments(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_prospect(pid)
    items = [a for a in store["assignments"].values() if a["prospect_id"] == pid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([ser_assignment(a) for a in page], limit, offset, total)


@bp.get("/advancement/prospects/<pid>/credit-splits")
def list_prospect_credit_splits(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_prospect(pid)
    items = [s for s in store["credit_splits"].values() if s["prospect_id"] == pid]
    credit_type = request.args.get("credit_type")
    if credit_type is not None:
        items = [s for s in items if s["credit_type"] == credit_type]
    page, limit, offset, total = paginate(items)
    return success_list([ser_credit_split(s) for s in page], limit, offset, total)


@bp.get("/advancement/prospects/<pid>/recognition")
def get_recognition(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    prospect = _get_prospect(pid)
    read = recognition_read(prospect)
    # lazy persistence of membership society (society maintenance is reflected
    # on the next recognition read)
    refresh_prospect_recognition(prospect)
    return success_object(read)


@bp.post("/advancement/prospects/<pid>/assessments")
def create_assessment(pid):
    user_id, role = authenticate()
    authorize(role, ["ProspectResearcher"])
    body = body_json()
    check_unknown_fields(body, {"assessed_capacity_cents", "engagement_score",
                                "philanthropy_score", "recency_score", "evidence_tier"})
    assessed_capacity_cents = req_money(body, "assessed_capacity_cents")
    engagement_score = req_int(body, "engagement_score", minimum=0, maximum=100)
    philanthropy_score = req_int(body, "philanthropy_score", minimum=0, maximum=100)
    recency_score = req_int(body, "recency_score", minimum=0, maximum=100)
    evidence_tier = req_enum(body, "evidence_tier",
                             {"SELF_REPORTED", "PUBLIC_RECORD", "VERIFIED_DOCUMENT"})
    prospect = _get_prospect(pid)
    if prospect["research_status"] == "DISQUALIFIED":
        fail(ERR_INVALID_MOVES_TRANSITION, "Cannot assess a DISQUALIFIED prospect")
    entity = new_entity()
    entity.update({
        "prospect_id": pid,
        "assessed_capacity_cents": assessed_capacity_cents,
        "engagement_score": engagement_score,
        "philanthropy_score": philanthropy_score,
        "recency_score": recency_score,
        "evidence_tier": evidence_tier,
        "adjusted_capacity_cents": None,
        "capacity_band_result": None,
        "affinity_score_result": None,
        "created_by": user_id,
        "reviewed_by": None,
        "review_rationale": None,
        "status": "SUBMITTED",
    })
    store["assessments"][entity["id"]] = entity
    # filing moves IDENTIFIED or RATED to IN_SCREENING; prior rating stays in force
    if prospect["research_status"] in ("IDENTIFIED", "RATED"):
        prospect["research_status"] = "IN_SCREENING"
    touch(prospect)
    return success_object(ser_assessment(entity), 201)


@bp.get("/advancement/prospects/<pid>/assessments")
def list_assessments(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_prospect(pid)
    items = [a for a in store["assessments"].values() if a["prospect_id"] == pid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([ser_assessment(a) for a in page], limit, offset, total)


@bp.post("/advancement/assessments/<aid>/review")
def review_assessment(aid):
    user_id, role = authenticate()
    authorize(role, ["AdvancementDirector"])
    body = body_json()
    check_unknown_fields(body, {"decision", "review_rationale"})
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    rationale = opt_str(body, "review_rationale")
    assessment = store["assessments"].get(aid)
    if assessment is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Assessment not found")
    # segregation of duties (priority 6) precedes the state precondition (8)
    if user_id == assessment["created_by"]:
        fail(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the assessment's creator")
    if assessment["status"] != "SUBMITTED":
        fail(ERR_ASSESSMENT_NOT_REVIEWABLE, "Assessment is not SUBMITTED")
    assessment["reviewed_by"] = user_id
    if rationale is not None:
        assessment["review_rationale"] = rationale
    if decision == "REJECT":
        assessment["status"] = "REJECTED"
        touch(assessment)
        return success_object(ser_assessment(assessment))
    # APPROVE: run capacity_affinity_rating and rate the prospect
    adjusted, band, affinity = capacity_affinity_rating(assessment)
    assessment["adjusted_capacity_cents"] = adjusted
    assessment["capacity_band_result"] = band
    assessment["affinity_score_result"] = affinity
    assessment["status"] = "APPROVED"
    touch(assessment)
    prospect = store["prospects"].get(assessment["prospect_id"])
    if prospect is not None and prospect["research_status"] != "DISQUALIFIED":
        # supersede any other APPROVED assessment of the same prospect
        for other in store["assessments"].values():
            if (other["prospect_id"] == prospect["id"] and other["id"] != assessment["id"]
                    and other["status"] == "APPROVED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        prospect["research_status"] = "RATED"
        prospect["capacity_band"] = band
        prospect["affinity_score"] = affinity
        prospect["rated_assessment_id"] = assessment["id"]
        prospect["rated_adjusted_capacity_cents"] = adjusted
        touch(prospect)
    return success_object(ser_assessment(assessment))
