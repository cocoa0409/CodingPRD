"""Referrals and funder reports."""
from flask import Blueprint, request

from db import STORE, logical_now
from errors import ApiError
from helpers import body, invalid, paginate, pagination_params, req_date, req_str
from middleware import ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT, forbidden, require_roles
from response import ok
from services.domain import (
    REFERRAL_TTL,
    compute_funder_report,
    new_common,
    new_log,
    ser_referral,
    ser_report,
    sort_by_creation,
    sweep_referral,
    touch,
)

bp = Blueprint("network", __name__)

REFERRAL_TARGETS = {"ACCEPTED", "DECLINED", "COMPLETED"}
REFERRAL_REACHABLE = {
    "SENT": {"ACCEPTED", "DECLINED"},
    "ACCEPTED": {"COMPLETED"},
    "DECLINED": set(),
    "COMPLETED": set(),
    "EXPIRED": set(),
}


def _load_referral(rid):
    rec = STORE["referrals"].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Referral not found.", 404)
    sweep_referral(rec)
    return rec


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@bp.post("/referrals")
def create_referral():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH)
    data = body()
    if role == ROLE_COACH:
        cid = data.get("coach_id")
        if cid is not None and cid != uid:
            forbidden("A coach may create referrals only under their own id.")
    participant_id = req_str(data, "participant_id")
    coach_id = req_str(data, "coach_id")
    partner_name = req_str(data, "partner_name")
    partner_type = req_str(data, "partner_type")
    if partner_type not in ("LENDER", "ASSISTANCE_PROGRAM"):
        invalid("Field 'partner_type' must be LENDER or ASSISTANCE_PROGRAM.")
    if role == ROLE_COACH and coach_id != uid:
        forbidden("A coach may create referrals only under their own id.")

    participant = STORE["participants"].get(participant_id)
    if participant is None:
        raise ApiError(
            "ERR_NOT_FOUND", "Referenced participant_id does not resolve.", 404
        )
    coach = STORE["coaches"].get(coach_id)
    if coach is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced coach_id does not resolve.", 404)

    now = logical_now()
    rec = new_common()
    rec.update(
        {
            "participant_id": participant_id,
            "coach_id": coach_id,
            "partner_name": partner_name,
            "partner_type": partner_type,
            "status": "SENT",
            "sent_at": now,
            "expires_at": now + REFERRAL_TTL,
        }
    )
    STORE["referrals"][rec["id"]] = rec
    return ok(ser_referral(rec), 201)


@bp.get("/referrals")
def list_referrals():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    # Expiry lazy sweep applies to every referral read, including lists.
    for ref in list(STORE["referrals"].values()):
        sweep_referral(ref)
    limit, offset = pagination_params()
    items = list(STORE["referrals"].values())
    if role == ROLE_PARTICIPANT:
        supplied = request.args.get("participant_id")
        if supplied is not None and supplied != uid:
            forbidden("Participants may read only their own referrals.")
        items = [r for r in items if r["participant_id"] == uid]
    for field in ("participant_id", "coach_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r[field] == v]
    items = sort_by_creation(items)
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_referral(r) for r in page], 200, pagination=page_meta)


@bp.get("/referrals/<rid>")
def get_referral(rid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["referrals"].get(rid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may read only their own referrals.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Referral not found.", 404)
    sweep_referral(rec)
    return ok(ser_referral(rec), 200)


@bp.post("/referrals/<rid>/transition")
def transition_referral(rid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH)
    rec = STORE["referrals"].get(rid)
    if rec is not None:
        sweep_referral(rec)
    if role == ROLE_COACH and rec is not None and rec["coach_id"] != uid:
        forbidden("A coach may manage only referrals they created.")
    data = body()
    target = data.get("target_state")
    if not isinstance(target, str) or target not in REFERRAL_TARGETS:
        invalid("Field 'target_state' must be one of ACCEPTED, DECLINED, COMPLETED.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Referral not found.", 404)
    if target not in REFERRAL_REACHABLE[rec["status"]]:
        raise ApiError(
            "ERR_INVALID_TRANSITION",
            "target_state %s is not reachable from %s." % (target, rec["status"]),
            409,
        )
    rec["status"] = target
    touch(rec)
    return ok(ser_referral(rec), 200)


# ---------------------------------------------------------------------------
# Funder reports (computed once, immutable)
# ---------------------------------------------------------------------------

@bp.post("/funder-reports")
def create_report():
    require_roles(ROLE_ADMIN)
    data = body()
    period_start_raw = req_str(data, "period_start")
    period_end_raw = req_str(data, "period_end")
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    if period_end <= period_start:
        invalid("Field 'period_end' must be after 'period_start'.")
    variant = req_str(data, "variant")
    if variant not in ("COHORT", "ROLLING"):
        invalid("Field 'variant' must be COHORT or ROLLING.")

    computed = compute_funder_report(period_start, period_end, variant)
    rec = new_log()
    rec.update(
        {
            "period_start": period_start_raw,
            "period_end": period_end_raw,
            "variant": variant,
            "participants_measured": computed["participants_measured"],
            "avg_credit_delta_points": computed["avg_credit_delta_points"],
            "avg_savings_delta_cents": computed["avg_savings_delta_cents"],
            "completions_count": computed["completions_count"],
        }
    )
    STORE["reports"][rec["id"]] = rec
    return ok(ser_report(rec), 201)


@bp.get("/funder-reports/<rid>")
def get_report(rid):
    require_roles(ROLE_ADMIN)
    rec = STORE["reports"].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Funder report not found.", 404)
    return ok(ser_report(rec), 200)
