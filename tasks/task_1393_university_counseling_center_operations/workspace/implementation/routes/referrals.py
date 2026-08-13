"""CommunityReferral endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERRAL_LOOP_EXHAUSTED,
    ERR_ENGAGEMENT_WINDOW,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("referrals", __name__)


@bp.route("/ucc/referrals/<referral_id>", methods=["GET"])
@require_roles("ReferralCoordinator", "Counselor", "ClinicalDirector", "TriageScreener")
def get_referral(referral_id: str, _user_id: str, _role: str):
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    return success_object(serialize(r))


@bp.route("/ucc/referrals", methods=["GET"])
@require_roles("ReferralCoordinator", "Counselor", "ClinicalDirector", "TriageScreener")
def list_referrals(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.referrals.values()))
    items = apply_filters(items, ["student_id", "episode_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/referrals/<referral_id>/match", methods=["POST"])
@require_roles("ReferralCoordinator")
def match_referral(referral_id: str, _user_id: str, _role: str):
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    body = get_json_body()
    provider_name = require_string(body, "provider_name")
    provider_specialty = require_string(body, "provider_specialty")
    if r.get("status") != "PENDING":
        raise_err(ERR_INVALID_STATE, "CommunityReferral is not PENDING")
    if provider_specialty != r.get("required_specialty"):
        raise_err(ERR_INVALID_REQUEST, "provider_specialty must equal required_specialty")
    r["status"] = "MATCHED"
    r["provider_name"] = provider_name
    db.touch(r)
    return success_object(serialize(r))


@bp.route("/ucc/referrals/<referral_id>/accept", methods=["POST"])
@require_roles("ReferralCoordinator")
def accept_referral(referral_id: str, _user_id: str, _role: str):
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    if r.get("status") != "MATCHED":
        raise_err(ERR_INVALID_STATE, "CommunityReferral is not MATCHED")
    r["status"] = "ACCEPTED"
    db.touch(r)
    # Fire care-side cascade: linked episode -> REFERRED_OUT (from OPEN or EXHAUSTED).
    ep_id = r.get("episode_id")
    if ep_id:
        ep = db.episodes.get(ep_id)
        if ep is not None and ep.get("status") in ("OPEN", "EXHAUSTED"):
            was_open = ep.get("status") == "OPEN"
            ep["status"] = "REFERRED_OUT"
            db.touch(ep)
            # REFERRED_OUT is terminal: the student's current term may change
            # (PRD §3.6); re-derive the strike recount and posture.
            student = db.students.get(ep.get("student_id"))
            if student is not None:
                domain.recompute_strikes_and_posture(student)
            if was_open:
                # Cancel remaining SCHEDULED sessions with reason REFERRED_OUT.
                for s in db.sessions.values():
                    if s.get("episode_id") == ep["id"] and s.get("status") == "SCHEDULED":
                        s["status"] = "CANCELLED_TIMELY"
                        s["cancellation_reason"] = "REFERRED_OUT"
                        db.touch(s)
    return success_object(serialize(r))


@bp.route("/ucc/referrals/<referral_id>/decline", methods=["POST"])
@require_roles("ReferralCoordinator")
def decline_referral(referral_id: str, _user_id: str, _role: str):
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    if r.get("status") != "MATCHED":
        raise_err(ERR_INVALID_STATE, "CommunityReferral is not MATCHED")
    r["status"] = "DECLINED"
    db.touch(r)
    return success_object(serialize(r))


@bp.route("/ucc/referrals/<referral_id>/rematch", methods=["POST"])
@require_roles("ReferralCoordinator")
def rematch_referral(referral_id: str, _user_id: str, _role: str):
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    if r.get("status") != "DECLINED":
        raise_err(ERR_INVALID_STATE, "CommunityReferral is not DECLINED")
    if int(r.get("rematch_count", 0)) >= 3:
        raise_err(ERR_REFERRAL_LOOP_EXHAUSTED, "Rematch loop cap (3) reached")
    r["status"] = "PENDING"
    r["provider_name"] = None
    r["rematch_count"] = int(r.get("rematch_count", 0)) + 1
    db.touch(r)
    return success_object(serialize(r))


@bp.route("/ucc/referrals/<referral_id>/confirm-engagement", methods=["POST"])
@require_roles("ReferralCoordinator")
def confirm_engagement(referral_id: str, _user_id: str, _role: str):
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    if r.get("status") != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "CommunityReferral is not ACCEPTED")
    # logical clock >= referral.updated_at + 14 days
    updated = db.parse_iso(r["updated_at"])
    threshold = updated + timedelta(days=domain.ENGAGEMENT_CONFIRM_DAYS)
    if db.clock() < threshold:
        raise_err(ERR_ENGAGEMENT_WINDOW, "Engagement window has not elapsed")
    r["status"] = "COMPLETED"
    db.touch(r)
    return success_object(serialize(r))
