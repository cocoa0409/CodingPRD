"""Firms, partners, engagements and engagement quality reviews (PRD 3.1 - 3.4)."""

from flask import Blueprint, request

import auth
import calc
import clock
import response
import shapes
import store
import vocab
from errors import ApiError

bp = Blueprint("firm", __name__)

A = auth.SYSTEM_ADMIN
FMP = auth.FIRM_MANAGING_PARTNER
EP = auth.ENGAGEMENT_PARTNER
QCD = auth.QUALITY_CONTROL_DIRECTOR
EQR = auth.ENGAGEMENT_QUALITY_REVIEWER
PRC = auth.PEER_REVIEW_COMMITTEE


# --------------------------------------------------------------------------- #
# 3.1 Firms
# --------------------------------------------------------------------------- #

@bp.post("/firms")
def create_firm():
    # The only endpoint exempt from the header-presence check: an unheadered attempt is
    # refused by the role check with ERR_ROLE_NOT_PERMITTED.
    auth.authenticate((A,), require_headers=False)
    body = shapes.body()
    shapes.require_present(body, ["legal_name", "state_code", "aa_hours_last_year",
                                  "peer_review_year_end"])
    legal_name = shapes.as_str(body, "legal_name", 1, 200)
    state_code = shapes.as_state_code(body, "state_code")
    aa_hours = shapes.as_int(body, "aa_hours_last_year", 0)
    year_end = shapes.as_date(body, "peer_review_year_end")
    program = "AICPA_PRC"
    if shapes.has(body, "enrolled_program"):
        program = shapes.as_enum(body, "enrolled_program", vocab.ENROLLED_PROGRAM)
    for existing in store.rows(store.FIRMS):
        if existing["legal_name"] == legal_name:
            raise ApiError("ERR_VALIDATION_FAILED", "legal_name must be unique.")
    firm = store.insert(store.FIRMS, {
        "legal_name": legal_name,
        "state_code": state_code,
        "aa_hours_last_year": aa_hours,
        "enrolled_program": program,
        "peer_review_year_end": year_end.isoformat(),
        "risk_posture": "STABLE",
        "open_deficiency_count": 0,
        "open_material_failure_count": 0,
        "critical_risk_count": 0,
        "last_peer_review_rating": "NONE",
        "prior_reviewer_ids": [],
        "unassigned_review_flag": False,
    })
    return response.object_response(store.serialize(store.FIRMS, firm), 201)


@bp.patch("/firms/<firm_id>")
def patch_firm(firm_id):
    auth.authenticate((A, PRC))
    firm = shapes.need_firm(firm_id)
    body = shapes.body()
    updates = {}
    if shapes.has(body, "aa_hours_last_year"):
        updates["aa_hours_last_year"] = shapes.as_int(body, "aa_hours_last_year", 0)
    if shapes.has(body, "peer_review_year_end"):
        updates["peer_review_year_end"] = shapes.as_date(
            body, "peer_review_year_end").isoformat()
    if shapes.has(body, "prior_reviewer_ids"):
        updates["prior_reviewer_ids"] = shapes.as_str_list(body, "prior_reviewer_ids")
    if shapes.has(body, "enrolled_program"):
        updates["enrolled_program"] = shapes.as_enum(
            body, "enrolled_program", vocab.ENROLLED_PROGRAM)
    store.mutate(firm, updates, force=True)
    return response.object_response(store.serialize(store.FIRMS, firm))


# --------------------------------------------------------------------------- #
# 3.2 Partners
# --------------------------------------------------------------------------- #

def _partner_inputs(body):
    out = {}
    if shapes.has(body, "cpe_hours_last_3y"):
        out["cpe_hours_last_3y"] = shapes.as_int(body, "cpe_hours_last_3y", 0)
    if shapes.has(body, "prior_engagement_team_clients"):
        out["prior_engagement_team_clients"] = shapes.as_client_history(
            body, "prior_engagement_team_clients")
    if shapes.has(body, "independence_conflict_client_names"):
        out["independence_conflict_client_names"] = shapes.as_str_list(
            body, "independence_conflict_client_names", 200)
    if shapes.has(body, "designations"):
        out["designations"] = shapes.as_enum_list(
            body, "designations", vocab.PARTNER_DESIGNATION)
    if shapes.has(body, "industry_specializations"):
        out["industry_specializations"] = shapes.as_enum_list(
            body, "industry_specializations", vocab.INDUSTRY_SPECIALIZATION)
    if shapes.has(body, "status"):
        out["status"] = shapes.as_enum(body, "status", vocab.PARTNER_STATUS)
    return out


@bp.post("/firms/<firm_id>/partners")
def create_partner(firm_id):
    actor = auth.authenticate((A, FMP))
    firm = shapes.need_firm(firm_id)
    body = shapes.body()
    shapes.require_present(body, ["full_name", "cpa_license_state"])
    full_name = shapes.as_str(body, "full_name", 1, 120)
    license_state = shapes.as_state_code(body, "cpa_license_state")
    extras = _partner_inputs(body)
    auth.require_same_firm(actor, firm["id"])
    fields = {
        "firm_id": firm["id"],
        "full_name": full_name,
        "cpa_license_state": license_state,
        "designations": [],
        "industry_specializations": [],
        "cpe_hours_last_3y": 0,
        "prior_engagement_team_clients": [],
        "independence_conflict_client_names": [],
        "status": "ACTIVE",
        "open_eqr_count": 0,
        "open_engagement_count": 0,
        "last_inspected_year": None,
        "eqr_eligible": False,
    }
    fields.update(extras)
    partner = store.insert(store.PARTNERS, fields)
    partner["eqr_eligible"] = (
        partner["status"] == "ACTIVE" and partner["cpe_hours_last_3y"] >= 120
        and "EQ_REVIEWER" in partner["designations"])
    return response.object_response(store.serialize(store.PARTNERS, partner), 201)


@bp.patch("/partners/<partner_id>")
def patch_partner(partner_id):
    actor = auth.authenticate((A, FMP))
    partner = shapes.need_partner(partner_id)
    body = shapes.body()
    updates = _partner_inputs(body)
    auth.require_same_firm(actor, partner["firm_id"])
    partner.update(updates)
    # PRD 2.4: version "increments by exactly 1 on every mutation of that row" - one
    # PATCH is one mutation, so the caller-supplied fields and the recomputed derived
    # values (eqr_eligible and the two counters) share a single version bump.
    calc.refresh_partner(partner, force=True)
    return response.object_response(store.serialize(store.PARTNERS, partner))


# --------------------------------------------------------------------------- #
# 3.2 Engagement acceptance
# --------------------------------------------------------------------------- #

@bp.post("/engagements")
def create_engagement():
    actor = auth.authenticate((A, FMP, EP))
    body = shapes.body()
    firm = shapes.need_firm(body.get("firm_id")) if shapes.has(body, "firm_id") else None
    partner = None
    if shapes.has(body, "engagement_partner_id"):
        partner = shapes.need_partner(body.get("engagement_partner_id"))
    shapes.require_present(body, ["firm_id", "client_name", "engagement_type",
                                  "period_end", "engagement_partner_id"])
    client_name = shapes.as_str(body, "client_name", 1, 200)
    period_end = shapes.as_date(body, "period_end")
    is_public = shapes.as_bool(body, "is_public_interest") \
        if shapes.has(body, "is_public_interest") else False
    is_first_year = shapes.as_bool(body, "is_first_year_client") \
        if shapes.has(body, "is_first_year_client") else False
    prior_findings = shapes.as_int(body, "prior_finding_count_3y", 0) \
        if shapes.has(body, "prior_finding_count_3y") else 0
    engagement_type = shapes.as_enum(body, "engagement_type", vocab.ENGAGEMENT_TYPE)

    auth.require_same_firm(actor, firm["id"])

    if partner["firm_id"] != firm["id"]:
        raise ApiError("ERR_PARTNER_FIRM_MISMATCH")
    if firm["risk_posture"] == "CRITICAL" and \
            engagement_type in vocab.MUST_SELECT_ENGAGEMENT_TYPES:
        raise ApiError("ERR_ACCEPTANCE_FROZEN")
    for existing in store.rows(store.ENGAGEMENTS):
        if existing["firm_id"] == firm["id"] and \
                existing["client_name"] == client_name and \
                existing["period_end"] == period_end.isoformat():
            raise ApiError("ERR_DUPLICATE_ENGAGEMENT")

    # partner.open_engagement_count as it stands BEFORE this engagement is inserted
    open_before = len([
        e for e in store.rows(store.ENGAGEMENTS)
        if e["engagement_partner_id"] == partner["id"]
        and e["workflow_state"] != "REPORT_RELEASED"])
    risk_score = calc.engagement_risk_score(
        engagement_type, is_first_year, is_public, prior_findings, open_before,
        partner["industry_specializations"])

    engagement = store.insert(store.ENGAGEMENTS, {
        "firm_id": firm["id"],
        "client_name": client_name,
        "engagement_type": engagement_type,
        "period_end": period_end.isoformat(),
        "is_public_interest": is_public,
        "is_first_year_client": is_first_year,
        "prior_finding_count_3y": prior_findings,
        "engagement_partner_id": partner["id"],
        "risk_score": risk_score,
        "eqr_required": False,
        "workflow_state": "PLANNING",
        "file_state": "OPEN",
        "eqr_concurred_at": None,
        "report_release_date": None,
        "reopened_count": 0,
    })
    engagement["eqr_required"] = calc.eqr_required(engagement, firm)
    calc.refresh_partner(partner)
    return response.object_response(store.serialize(store.ENGAGEMENTS, engagement), 201)


# --------------------------------------------------------------------------- #
# 3.3 The engagement's twin lifecycles
# --------------------------------------------------------------------------- #

WORKFLOW_NEXT = {
    "PLANNING": ("FIELDWORK",),
    "FIELDWORK": ("EQR_PENDING",),
    "EQR_PENDING": ("EQR_CLEARED",),
    "EQR_CLEARED": ("REPORT_RELEASED",),
    "REPORT_RELEASED": (),
}

FILE_NEXT = {
    "OPEN": ("ASSEMBLED",),
    "ASSEMBLED": ("LOCKED",),
    "LOCKED": (),
}


@bp.post("/engagements/<engagement_id>/workflow-transitions")
def workflow_transition(engagement_id):
    actor = auth.authenticate((A, EP, FMP))
    engagement = shapes.need_engagement(engagement_id)
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.WORKFLOW_STATE)
    auth.require_owner(actor, engagement["engagement_partner_id"])
    auth.require_same_firm(actor, engagement["firm_id"])
    # Once LOCKED both dimensions are frozen: any further transition is refused here.
    if engagement["file_state"] == "LOCKED":
        raise ApiError("ERR_ENGAGEMENT_FILE_LOCKED")
    if to_state not in WORKFLOW_NEXT[engagement["workflow_state"]]:
        raise ApiError("ERR_INVALID_TRANSITION")

    updates = {"workflow_state": to_state}
    if to_state == "EQR_CLEARED":
        concurred = None
        if engagement["eqr_required"]:
            for review in store.rows(store.QUALITY_REVIEWS):
                if review["engagement_id"] == engagement["id"] and \
                        review["state"] == "CONCURRED":
                    concurred = review
                    break
            if concurred is None:
                raise ApiError("ERR_EQR_NOT_CONCURRED")
            updates["eqr_concurred_at"] = concurred["concluded_at"]
        else:
            updates["eqr_concurred_at"] = None
    elif to_state == "REPORT_RELEASED":
        updates["report_release_date"] = clock.today().isoformat()

    store.mutate(engagement, updates, force=True)
    if to_state == "REPORT_RELEASED":
        partner = store.get(store.PARTNERS, engagement["engagement_partner_id"])
        if partner is not None:
            calc.refresh_partner(partner)
    return response.object_response(store.serialize(store.ENGAGEMENTS, engagement))


@bp.post("/engagements/<engagement_id>/file-transitions")
def file_transition(engagement_id):
    actor = auth.authenticate((A, EP, QCD))
    engagement = shapes.need_engagement(engagement_id)
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.FILE_STATE)
    auth.require_owner(actor, engagement["engagement_partner_id"])
    auth.require_same_firm(actor, engagement["firm_id"])
    if engagement["file_state"] == "LOCKED":
        raise ApiError("ERR_ENGAGEMENT_FILE_LOCKED")
    if to_state not in FILE_NEXT[engagement["file_state"]]:
        raise ApiError("ERR_INVALID_TRANSITION")

    if to_state == "ASSEMBLED":
        if engagement["workflow_state"] not in ("EQR_CLEARED", "REPORT_RELEASED"):
            raise ApiError("ERR_INVALID_TRANSITION")
    else:
        if engagement["workflow_state"] != "REPORT_RELEASED":
            raise ApiError("ERR_INVALID_TRANSITION")
        released = clock.parse_date(engagement["report_release_date"])
        if released is None or clock.days_between(clock.today(), released) > 60:
            raise ApiError("ERR_DOCUMENTATION_WINDOW_CLOSED")

    store.mutate(engagement, {"file_state": to_state}, force=True)
    return response.object_response(store.serialize(store.ENGAGEMENTS, engagement))


# --------------------------------------------------------------------------- #
# 3.4 Engagement quality review
# --------------------------------------------------------------------------- #

@bp.post("/engagements/<engagement_id>/quality-reviews")
def assign_quality_review(engagement_id):
    actor = auth.authenticate((A, FMP, QCD))
    engagement = shapes.need_engagement(engagement_id)
    body = shapes.body()
    candidate = None
    if shapes.has(body, "reviewer_partner_id"):
        candidate = shapes.need_partner(body.get("reviewer_partner_id"))
    shapes.require_present(body, ["reviewer_partner_id", "expected_engagement_version"])
    attested = None
    if shapes.has(body, "objectivity_attested"):
        attested = shapes.as_bool(body, "objectivity_attested")
    auth.require_same_firm(actor, engagement["firm_id"])
    shapes.check_version(body, "expected_engagement_version", engagement)
    if engagement["file_state"] == "LOCKED":
        raise ApiError("ERR_ENGAGEMENT_FILE_LOCKED")
    if engagement["workflow_state"] not in ("FIELDWORK", "EQR_PENDING"):
        raise ApiError("ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW")

    cooling_off = calc.eqr_reviewer_eligibility(engagement, candidate, attested)
    calc.eqr_concurrency_check(engagement, candidate)

    review = store.insert(store.QUALITY_REVIEWS, {
        "engagement_id": engagement["id"],
        "reviewer_partner_id": candidate["id"],
        "assigned_at": clock.now_iso(),
        "concluded_at": None,
        "objectivity_attested": attested,
        "cooling_off_days_at_assignment": cooling_off,
        "concern_round_count": 0,
        "last_concern_summary": None,
        "state": "ASSIGNED",
    })
    calc.refresh_partner(candidate)
    store.mutate(engagement, {}, force=True)
    return response.object_response(store.serialize(store.QUALITY_REVIEWS, review), 201)


EQR_NEXT = {
    "ASSIGNED": ("IN_PROGRESS", "WITHDRAWN"),
    "IN_PROGRESS": ("CONCERNS_RAISED", "CONCURRED"),
    "CONCERNS_RAISED": ("IN_PROGRESS", "WITHDRAWN"),
    "CONCURRED": (),
    "WITHDRAWN": (),
}


@bp.post("/quality-reviews/<eqr_id>/transitions")
def quality_review_transition(eqr_id):
    actor = auth.authenticate((A, EQR, FMP))
    review = shapes.need_review(eqr_id)
    engagement = store.get(store.ENGAGEMENTS, review["engagement_id"])
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.EQR_STATE)
    concern_summary = None
    if to_state == "CONCERNS_RAISED":
        shapes.require_present(body, ["concern_summary"])
        concern_summary = shapes.as_str(body, "concern_summary", 1, 500)
    auth.require_owner(actor, review["reviewer_partner_id"], roles=(EQR,))
    if engagement is not None:
        auth.require_same_firm(actor, engagement["firm_id"])

    current = review["state"]
    if to_state == "CONCURRED" and current == "CONCERNS_RAISED":
        raise ApiError("ERR_UNRESOLVED_CONCERNS")
    if to_state not in EQR_NEXT[current]:
        raise ApiError("ERR_INVALID_TRANSITION")
    if to_state == "IN_PROGRESS" and current == "CONCERNS_RAISED":
        if engagement is None or engagement["workflow_state"] != "EQR_PENDING":
            raise ApiError("ERR_INVALID_TRANSITION")

    updates = {"state": to_state}
    if to_state == "CONCERNS_RAISED":
        updates["concern_round_count"] = review["concern_round_count"] + 1
        updates["last_concern_summary"] = concern_summary
    if to_state in ("CONCURRED", "WITHDRAWN"):
        updates["concluded_at"] = clock.now_iso()
    store.mutate(review, updates, force=True)

    if to_state == "CONCERNS_RAISED" and engagement is not None and \
            engagement["workflow_state"] == "EQR_PENDING":
        store.mutate(engagement,
                     {"workflow_state": "FIELDWORK", "eqr_concurred_at": None},
                     force=True)
    if to_state in ("CONCURRED", "WITHDRAWN"):
        partner = store.get(store.PARTNERS, review["reviewer_partner_id"])
        if partner is not None:
            calc.refresh_partner(partner)
    if to_state == "WITHDRAWN" and engagement is not None:
        # The linked engagement's version is incremented by 1, invalidating any
        # expected_engagement_version the client observed before the withdrawal.
        store.mutate(engagement, {}, force=True)
    return response.object_response(store.serialize(store.QUALITY_REVIEWS, review))
