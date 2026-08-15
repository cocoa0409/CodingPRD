"""IndependentReviewReferral endpoints (PRD section 3.6)."""

from flask import Blueprint

import calc
import db
import errors
from auth import require_roles
from envelope import success_object
from serializers import referral_out
from services import (append_event, create_effectuation, get_case_or_404,
                      get_or_404, guard_entity_status, guard_status)
from validate import get_body, opt_int, req_enum, req_str

bp = Blueprint("ire", __name__)

IRE_DECISIONS = {"UPHOLD_PLAN", "OVERTURN_PLAN", "PARTIAL"}
REFERRAL_TERMINAL = ("EFFECTUATED",)


@bp.route("/appeals/cases/<cid>/ire-referrals", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def forward_to_ire(cid, _user_id, _role):
    case = get_case_or_404(cid)
    body = get_body()
    ire_organization_code = req_str(body, "ire_organization_code")
    guard_status(case, ("NOTIFIED",))
    if not (case["case_kind"] == "APPEAL"
            and case["decision_outcome"] != "FULLY_FAVORABLE"):
        raise errors.invalid_state(
            "only APPEAL cases with adverse or partial outcomes go to the IRE")
    # IRE forwarding window (priority 10): within 72h of decided_at
    if (db.clock_now() - case["decided_at"]).total_seconds() \
            > calc.IRE_FORWARD_WINDOW_HOURS * 3600:
        raise errors.ire_window_missed()
    ref = db.make_common()
    ref.update({
        "case_id": case["id"],
        "ire_organization_code": ire_organization_code,
        "status": "FORWARDED",
        "forwarded_at": db.clock_now(),
        "ire_decision": None,
        "ire_decision_received_at": None,
    })
    db.referrals[ref["id"]] = ref
    case["status"] = "IRE_REFERRED"
    append_event(case, "IRE_FORWARDED", _role, _user_id)
    db.touch(case)
    return success_object(referral_out(ref), status=201)


@bp.route("/appeals/ire-referrals/<rid>", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer"})
def get_referral(rid, _user_id, _role):
    return success_object(referral_out(get_or_404(db.referrals, rid, "referral")))


@bp.route("/appeals/ire-referrals/<rid>/ire-acknowledge", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def ire_acknowledge(rid, _user_id, _role):
    ref = get_or_404(db.referrals, rid, "referral")
    guard_entity_status(ref, ("FORWARDED",), REFERRAL_TERMINAL, "referral")
    ref["status"] = "ACKNOWLEDGED_BY_IRE"
    db.touch(ref)
    return success_object(referral_out(ref))


@bp.route("/appeals/ire-referrals/<rid>/ire-record-decision", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def ire_record_decision(rid, _user_id, _role):
    ref = get_or_404(db.referrals, rid, "referral")
    guard_entity_status(ref, ("ACKNOWLEDGED_BY_IRE",), REFERRAL_TERMINAL,
                        "referral")
    body = get_body()
    ire_decision = req_enum(body, "ire_decision", IRE_DECISIONS)
    payment = opt_int(body, "payment_amount_cents", None)
    if payment is not None and payment < 0:
        raise errors.validation("payment_amount_cents must be >= 0")
    ref["ire_decision"] = ire_decision
    ref["ire_decision_received_at"] = db.clock_now()
    ref["status"] = "DECISION_RECEIVED"
    if ire_decision in ("OVERTURN_PLAN", "PARTIAL"):
        case = db.cases[ref["case_id"]]
        create_effectuation(case, payment if payment is not None else 0,
                            referral_id=ref["id"])
    db.touch(ref)
    return success_object(referral_out(ref))
