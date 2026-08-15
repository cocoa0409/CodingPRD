"""Referral respond / withdraw (PRD section 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, now
from errors import (ERR_INVALID_CASE_STATE, ERR_INVALID_REFERRAL_STATE,
                    ERR_PANEL_CAPACITY_REACHED, ERR_PANEL_MEMBER_NOT_ACTIVE,
                    ERR_PANEL_WINDOW_OVERLAP, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services import derived
from services.common import get_or_404, list_response, touch
from services.serialize import referral_json
from validators import (as_date, body, check_allowed, opt_str, req_date,
                        req_enum)

bp = Blueprint("referrals", __name__)

ADVICE_WINDOW_DAYS = 30


@bp.route("/referrals/<rid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_referral(rid):
    return ok_object(referral_json(get_or_404(db.referrals, rid)))


@bp.route("/referrals", methods=["GET"])
@require_roles(ALL_ROLES)
def list_referrals():
    records = list(db.referrals.values())
    for param in ("case_id", "panel_member_id", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if r[param] == value]
    return list_response(records, referral_json)


def _half_open_overlap(s1, e1, s2, e2):
    """[s1, e1) overlaps [s2, e2); mere adjacency (end == start) is not overlap."""
    return s1 < e2 and s2 < e1


@bp.route("/referrals/<rid>/respond", methods=["POST"])
@require_roles(["SupervisingAttorney", "ProgramDirector"])
def respond_referral(rid):
    ref = get_or_404(db.referrals, rid)
    b = body()
    check_allowed(b, ["decision", "service_start_date", "service_end_date",
                      "decline_reason"])
    decision = req_enum(b, "decision", ["ACCEPT", "DECLINE"])
    start_s = end_s = None
    if decision == "ACCEPT":
        start_s = req_date(b, "service_start_date")
        end_s = req_date(b, "service_end_date")
        if as_date(end_s) <= as_date(start_s):
            from errors import ERR_INVALID_REQUEST
            fail(ERR_INVALID_REQUEST,
                 "service_end_date must be after service_start_date")
    decline_reason = opt_str(b, "decline_reason")
    # State legality.
    if ref["status"] != "OFFERED":
        fail(ERR_INVALID_REFERRAL_STATE,
             "Only an OFFERED referral can be responded to")

    if decision == "ACCEPT":
        member = db.panel_members.get(ref["panel_member_id"])
        if member is None or member["status"] != "ACTIVE":
            fail(ERR_PANEL_MEMBER_NOT_ACTIVE, "Panel member is not ACTIVE")
        if derived.panel_active_count(member["id"]) >= member["max_active_referrals"]:
            fail(ERR_PANEL_CAPACITY_REACHED,
                 "Panel member is at their active referral cap")
        new_start, new_end = as_date(start_s), as_date(end_s)
        for other in db.referrals.values():
            if (other["panel_member_id"] == member["id"]
                    and other["status"] == "ACCEPTED"
                    and other["id"] != ref["id"]
                    and _half_open_overlap(new_start, new_end,
                                           as_date(other["service_start_date"]),
                                           as_date(other["service_end_date"]))):
                fail(ERR_PANEL_WINDOW_OVERLAP,
                     "Service window overlaps another accepted referral")
        # Accept side effects.
        ref["status"] = "ACCEPTED"
        ref["responded_at"] = now()
        ref["service_start_date"] = start_s
        ref["service_end_date"] = end_s
        touch(ref)
        case = db.cases.get(ref["case_id"])
        if case is not None:
            case["placement"] = "PRO_BONO"
            if case["status"] == "PENDING_ASSIGNMENT":
                case["status"] = "OPEN"
                if case["opened_at"] is None:
                    case["opened_at"] = now()
                if (case["service_level"] == "ADVICE_ONLY"
                        and case["advice_deadline"] is None):
                    case["advice_deadline"] = case["opened_at"] + timedelta(
                        days=ADVICE_WINDOW_DAYS)
            touch(case)
        if member is not None:
            touch(member)  # active_referral_count rose (derived)
    else:
        ref["status"] = "DECLINED"
        ref["responded_at"] = now()
        ref["decline_reason"] = decline_reason
        touch(ref)
    return ok_object(referral_json(ref))


@bp.route("/referrals/<rid>/withdraw", methods=["POST"])
@require_roles(["SupervisingAttorney"])
def withdraw_referral(rid):
    ref = get_or_404(db.referrals, rid)
    b = body()
    check_allowed(b, ["withdrawal_reason"])
    opt_str(b, "withdrawal_reason")
    if ref["status"] not in ("OFFERED", "ACCEPTED"):
        fail(ERR_INVALID_REFERRAL_STATE,
             "Only OFFERED or ACCEPTED referrals can be withdrawn")
    if ref["status"] == "ACCEPTED":
        case = db.cases.get(ref["case_id"])
        if case is not None and case["status"] == "CLOSED":
            fail(ERR_INVALID_CASE_STATE,
                 "Cannot withdraw an accepted referral for a closed case")
        if case is not None:
            case["placement"] = "INTERNAL"
            if (case["assigned_attorney_id"] is None
                    and case["status"] == "OPEN"):
                case["status"] = "PENDING_ASSIGNMENT"
            touch(case)
        member = db.panel_members.get(ref["panel_member_id"])
        if member is not None:
            touch(member)  # active_referral_count fell (derived)
    ref["status"] = "WITHDRAWN"
    touch(ref)
    return ok_object(referral_json(ref))
