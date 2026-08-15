"""Referral endpoints: send on creation, three dispositions (PRD section 3.6)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASE_NOT_OPEN,
    ERR_NOT_FOUND,
    ERR_REFERRAL_NOT_SENT,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import get_json_body, require_enum, require_string

bp = Blueprint("referrals", __name__)

REFERRAL_TYPES = {"LAW_ENFORCEMENT", "MENTAL_HEALTH"}
URGENCIES = {"ROUTINE", "URGENT"}


def _get_referral_or_404(referral_id: str) -> dict:
    referral = db.referrals.get(referral_id)
    if referral is None:
        raise_err(ERR_NOT_FOUND, "Referral id does not exist")
    return referral


@bp.route("/referrals", methods=["POST"])
@require_roles("ThreatAssessor", "TeamLead")
def create_referral(_user_id: str, _role: str):
    body = get_json_body()
    case_id = require_string(body, "case_id")
    referral_type = require_enum(body, "referral_type", REFERRAL_TYPES)
    agency_name = require_string(body, "agency_name")
    urgency = require_enum(body, "urgency", URGENCIES)

    case = domain.get_case_or_404(case_id)
    if case["status"] not in domain.REFERRAL_OPEN_CASE_STATUSES:
        raise_err(ERR_CASE_NOT_OPEN,
                  "Referral creation requires a non-terminal case status")

    # Creation IS the send.
    referral = domain.create_referral(case, referral_type, agency_name, urgency, False)
    domain.audit(case["id"], "REFERRAL_SENT",
                 f"{referral_type} referral sent to {agency_name} at {urgency} urgency",
                 _user_id, _role)
    return success_object(db.public(referral), 201)


@bp.route("/referrals/<referral_id>/acknowledge", methods=["POST"])
@require_roles("ThreatAssessor", "TeamLead")
def acknowledge_referral(referral_id: str, _user_id: str, _role: str):
    referral = _get_referral_or_404(referral_id)
    if referral["status"] != "SENT":
        raise_err(ERR_REFERRAL_NOT_SENT, "Acknowledge requires referral status SENT")
    referral["status"] = "ACKNOWLEDGED"
    db.touch(referral)
    domain.audit(referral["case_id"], "REFERRAL_ACKNOWLEDGED",
                 f"Referral {referral_id} acknowledged by the receiving agency",
                 _user_id, _role)
    return success_object(db.public(referral))


@bp.route("/referrals/<referral_id>/decline", methods=["POST"])
@require_roles("ThreatAssessor", "TeamLead")
def decline_referral(referral_id: str, _user_id: str, _role: str):
    body = get_json_body()
    decline_reason = require_string(body, "decline_reason")

    referral = _get_referral_or_404(referral_id)
    if referral["status"] != "SENT":
        raise_err(ERR_REFERRAL_NOT_SENT, "Decline requires referral status SENT")
    referral["status"] = "DECLINED"
    referral["decline_reason"] = decline_reason
    db.touch(referral)
    domain.audit(referral["case_id"], "REFERRAL_DECLINED",
                 f"Referral {referral_id} declined: {decline_reason}", _user_id, _role)
    return success_object(db.public(referral))


@bp.route("/referrals/<referral_id>/withdraw", methods=["POST"])
@require_roles("ThreatAssessor", "TeamLead")
def withdraw_referral(referral_id: str, _user_id: str, _role: str):
    referral = _get_referral_or_404(referral_id)
    if referral["status"] != "SENT":
        raise_err(ERR_REFERRAL_NOT_SENT, "Withdraw requires referral status SENT")
    referral["status"] = "WITHDRAWN"
    db.touch(referral)
    domain.audit(referral["case_id"], "REFERRAL_WITHDRAWN",
                 f"Referral {referral_id} withdrawn (compensates the send)",
                 _user_id, _role)
    return success_object(db.public(referral))
