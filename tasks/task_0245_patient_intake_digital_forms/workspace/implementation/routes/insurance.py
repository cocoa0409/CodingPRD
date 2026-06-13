"""InsuranceCard + eligibility routes (PRD §3.5, §3.6) and EligibilityCheck reads."""
from flask import Blueprint, request

import db
import serialize
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_SESSION_EXPIRED,
    ERR_CARD_NOT_VERIFIABLE,
    ERR_CARD_NOT_VERIFYING,
    ERR_INVALID_OUTCOME,
)
from middleware import require_roles
from response import success, success_list
from services import calculations
from services.common import touch, require_string, opt_int
from services.lookups import get_session, get_card, get_eligibility_check
from services.pagination import paginate
from services import sessions as S

bp = Blueprint("insurance", __name__)


def _first_in_progress(session):
    """Advance DRAFT -> IN_PROGRESS on first child create (PRD §3.3)."""
    if session["workflow_status"] == "DRAFT":
        if S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired")
        session["workflow_status"] = "IN_PROGRESS"
        touch(session)


@bp.route("/insurance-cards", methods=["POST"])
@require_roles("FrontDeskStaff")
def create_card():
    body = request.get_json(silent=True) or {}
    intake_session_id = require_string(body, "intake_session_id")
    payer_name = require_string(body, "payer_name")
    member_id = require_string(body, "member_id")
    session = get_session(intake_session_id)

    def nonneg(name):
        val = opt_int(body, name, 0)
        if val < 0:
            raise err(ERR_INVALID_REQUEST, f"{name} must be non-negative")
        return val

    plan_copay_cents = nonneg("plan_copay_cents")
    plan_coinsurance_pct = nonneg("plan_coinsurance_pct")
    facility_coinsurance_pct = nonneg("facility_coinsurance_pct")
    remaining_deductible_cents = nonneg("remaining_deductible_cents")
    visit_allowed_amount_cents = nonneg("visit_allowed_amount_cents")
    if plan_coinsurance_pct > 100 or facility_coinsurance_pct > 100:
        raise err(ERR_INVALID_REQUEST, "coinsurance percent must be 0-100")

    with db.LOCK:
        _first_in_progress(session)
        now = db.now_iso()
        card = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "intake_session_id": intake_session_id,
            "payer_name": payer_name,
            "member_id": member_id,
            "plan_copay_cents": plan_copay_cents,
            "plan_coinsurance_pct": plan_coinsurance_pct,
            "facility_coinsurance_pct": facility_coinsurance_pct,
            "remaining_deductible_cents": remaining_deductible_cents,
            "visit_allowed_amount_cents": visit_allowed_amount_cents,
            "eligibility_status": "UNVERIFIED",
        }
        db.insurance_cards[card["id"]] = card
    return success(serialize.insurance_card(card), status=201)


@bp.route("/insurance-cards/<cid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_card_route(cid):
    card = get_card(cid)
    return success(serialize.insurance_card(card), status=200)


@bp.route("/insurance-cards", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_cards():
    records = list(db.insurance_cards.values())
    val = request.args.get("intake_session_id")
    if val is not None:
        records = [r for r in records if r["intake_session_id"] == val]
    items, limit, offset, total = paginate(records, serialize.insurance_card)
    return success_list(items, limit, offset, total)


@bp.route("/insurance-cards/<cid>/verify", methods=["POST"])
@require_roles("FrontDeskStaff")
def verify_card(cid):
    card = get_card(cid)
    with db.LOCK:
        if card["eligibility_status"] not in {"UNVERIFIED", "NEEDS_REVIEW"}:
            raise err(ERR_CARD_NOT_VERIFIABLE, "card not verifiable")
        session = db.intake_sessions[card["intake_session_id"]]
        if session["workflow_status"] in {"EXPIRED", "CANCELLED"} or S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired or cancelled")
        card["eligibility_status"] = "VERIFYING"
        touch(card)
    return success(serialize.insurance_card(card), status=200)


@bp.route("/insurance-cards/<cid>/resolve-eligibility", methods=["POST"])
@require_roles("FrontDeskStaff")
def resolve_eligibility(cid):
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if not isinstance(outcome, str):
        raise err(ERR_INVALID_REQUEST, "outcome is required")
    if outcome not in {"ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW"}:
        raise err(ERR_INVALID_OUTCOME, "invalid outcome")

    card = get_card(cid)
    with db.LOCK:
        if card["eligibility_status"] != "VERIFYING":
            raise err(ERR_CARD_NOT_VERIFYING, "card not verifying")

        session = db.intake_sessions[card["intake_session_id"]]
        clinic = db.clinics[session["clinic_id"]]
        facility_fee = clinic["facility_fee_cents"]
        copay_rounding = clinic["copay_rounding"]

        # Provisional figure recorded on the EligibilityCheck (deductible-unmet).
        provisional = calculations.provisional_responsibility(card, facility_fee)

        # Append-only EligibilityCheck: id + created_at only (PRD §2.4).
        now = db.now_iso()
        check = {
            "id": db.new_id(),
            "created_at": now,
            "_seq": db.next_seq(),
            "insurance_card_id": card["id"],
            "intake_session_id": session["id"],
            "outcome": outcome,
            "provisional_responsibility_cents": provisional,
        }
        db.eligibility_checks[check["id"]] = check

        card["eligibility_status"] = outcome
        touch(card)

        if outcome == "ELIGIBLE":
            final = calculations.finalize_eligible(card, facility_fee, copay_rounding)
            session["final_patient_responsibility_cents"] = final
            touch(session)
            # Cascade financial_status (PRD §3.5).
            if final == 0:
                S.set_financial(session, "INSURED")
            else:
                S.set_financial(session, "COPAY_DUE")
        elif outcome == "INELIGIBLE":
            final = calculations.finalize_self_pay(card, facility_fee)
            session["final_patient_responsibility_cents"] = final
            touch(session)
            S.set_financial(session, "SELF_PAY")
        # NEEDS_REVIEW: records the check but does not resolve eligibility.

        # Eligibility resolution may flip forms_complete and readiness (PRD §3.4).
        S.bubble_up(session)
    return success(serialize.insurance_card(card), status=200)


# --------------------------------------------------------------------------
# EligibilityCheck reads
# --------------------------------------------------------------------------
@bp.route("/eligibility-checks/<eid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_eligibility_check_route(eid):
    check = get_eligibility_check(eid)
    return success(serialize.eligibility_check(check), status=200)


@bp.route("/eligibility-checks", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_eligibility_checks():
    records = list(db.eligibility_checks.values())
    for f in ("insurance_card_id", "intake_session_id"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    items, limit, offset, total = paginate(records, serialize.eligibility_check)
    return success_list(items, limit, offset, total)
