"""Claims: intake with TPA selector assignment, adjudication under capped
authority, payment from trust, and the bounded deny/reopen loop
(PRD section 3.6)."""
from datetime import timedelta

from flask import Blueprint, g, request

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_OUTSIDE_COVERAGE_PERIOD, ERR_REPORTING_DEADLINE_MISSED,
    ERR_NO_ELIGIBLE_TPA, ERR_APPOINTMENT_NOT_ACTIVE,
    ERR_AUTHORITY_LIMIT_EXCEEDED, ERR_APPROVED_EXCEEDS_CLAIMED,
    ERR_TRUST_INSUFFICIENT_FUNDS, ERR_REOPEN_LIMIT_EXCEEDED,
    ERR_REOPEN_WINDOW_CLOSED,
)
from middleware import require_roles, require_carrier_owner, require_tpa_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from services import trust
from services.selector import select_appointment
from validation import get_body, req_str, req_enum, req_int, req_int_pos, req_datetime

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"PROPERTY_DAMAGE", "BODILY_INJURY", "LIABILITY", "OTHER"}
REPORTING_DEADLINE_DAYS = 60
MAX_REOPENS = 2
REOPEN_WINDOW_DAYS = 90


def _assigned_appointment(claim):
    appt_id = claim.get("_appointment_id")
    if appt_id is None:
        return None
    return STORE.tpa_appointments.get(appt_id)


def _require_appointment_active(claim):
    appt = _assigned_appointment(claim)
    if appt is None or appt["status"] != "ACTIVE":
        raise_err(ERR_APPOINTMENT_NOT_ACTIVE, "The appointment under which the claim was assigned is not ACTIVE.")
    return appt


@bp.post("/mga/policies/<policyId>/claims")
def report_claim(policyId):
    require_roles("MGAUnderwriter")
    policy = get_or_404(STORE.policies, policyId, "Policy")
    body = get_body()
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    occurrence_date = req_datetime(body, "occurrence_date")
    amount_claimed_cents = req_int_pos(body, "amount_claimed_cents")
    clock = now_dt()
    # Stage 9: temporal guards.
    if not (policy["effective_from"] <= occurrence_date < policy["effective_to"]):
        raise_err(ERR_OUTSIDE_COVERAGE_PERIOD, "occurrence_date is outside the policy term [effective_from, effective_to).")
    if clock - occurrence_date > timedelta(days=REPORTING_DEADLINE_DAYS):
        raise_err(ERR_REPORTING_DEADLINE_MISSED, "occurrence_date is more than 60 days before the report clock.")
    # Stage 11: TPA selector; empty candidate set rejects the report.
    appointment = select_appointment(policy["program_id"], claim_type, occurrence_date)
    if appointment is None:
        raise_err(ERR_NO_ELIGIBLE_TPA, "No ACTIVE appointment covers this claim type and occurrence date.")
    c = new_entity()
    c.update({
        "policy_id": policy["id"],
        "program_id": policy["program_id"],
        "assigned_tpa_id": appointment["tpa_id"],
        "_appointment_id": appointment["id"],
        "claim_type": claim_type,
        "occurrence_date": occurrence_date,
        "amount_claimed_cents": amount_claimed_cents,
        "case_reserve_cents": 0,
        "approved_amount_cents": None,
        "paid_cents": 0,
        "status": "REPORTED",
        "denial_reason": None,
        "denied_at": None,
        "reopened_count": 0,
        "paid_at": None,
        "referral_reason": None,
        "reported_claim_bordereau_id": None,
    })
    STORE.claims[c["id"]] = c
    return success_object(serialize.claim(c), status=201)


@bp.get("/mga/policies/<policyId>/claims")
def list_policy_claims(policyId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.policies, policyId, "Policy")
    items = filter_query(
        [c for c in STORE.claims.values() if c["policy_id"] == policyId],
        status=request.args.get("status"),
    )
    return render_list(items, serialize.claim)


@bp.get("/mga/claims/<claimId>")
def get_claim(claimId):
    require_roles(*ALL_ROLES)
    c = get_or_404(STORE.claims, claimId, "Claim")
    return success_object(serialize.claim(c))


@bp.get("/mga/claims")
def list_claims():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.claims.values()),
        program_id=request.args.get("program_id"),
        assigned_tpa_id=request.args.get("assigned_tpa_id"),
        policy_id=request.args.get("policy_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.claim)


@bp.post("/mga/claims/<claimId>/start-review")
def start_review(claimId):
    require_roles("TPAAdjuster")
    c = get_or_404(STORE.claims, claimId, "Claim")
    require_tpa_owner(c)
    if c["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "Only a REPORTED claim can move to UNDER_REVIEW.")
    _require_appointment_active(c)
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/set-reserve")
def set_reserve(claimId):
    require_roles("TPAAdjuster")
    c = get_or_404(STORE.claims, claimId, "Claim")
    require_tpa_owner(c)
    body = get_body()
    case_reserve_cents = req_int(body, "case_reserve_cents")
    if case_reserve_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "Field 'case_reserve_cents' must be >= 0.")
    if c["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Reserves may be set only while the claim is UNDER_REVIEW.")
    c["case_reserve_cents"] = case_reserve_cents
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/refer")
def refer_claim(claimId):
    require_roles("TPAAdjuster")
    c = get_or_404(STORE.claims, claimId, "Claim")
    require_tpa_owner(c)
    if c["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an UNDER_REVIEW claim can be referred.")
    c["status"] = "REFERRED"
    c["referral_reason"] = "ADJUSTER_ESCALATION"
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/approve")
def approve_claim(claimId):
    require_roles("TPAAdjuster", "CarrierUnderwriter")
    c = get_or_404(STORE.claims, claimId, "Claim")
    program = STORE.programs[c["program_id"]]
    body = get_body()
    approved_amount_cents = req_int(body, "approved_amount_cents")
    if g.user_role == "TPAAdjuster":
        require_tpa_owner(c)
        if c["status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "A TPA adjuster may approve only from UNDER_REVIEW.")
        appt = _require_appointment_active(c)
        # The safety ceiling is evaluated before the amount-versus-claimed check.
        if approved_amount_cents > appt["authority_limit_cents"]:
            raise_err(ERR_AUTHORITY_LIMIT_EXCEEDED, "approved_amount_cents exceeds the appointment's authority_limit_cents.")
    else:
        require_carrier_owner(program)
        if c["status"] not in ("UNDER_REVIEW", "REFERRED"):
            raise_err(ERR_INVALID_STATE, "The carrier may approve only from UNDER_REVIEW or REFERRED.")
    if approved_amount_cents > c["amount_claimed_cents"]:
        raise_err(ERR_APPROVED_EXCEEDS_CLAIMED, "approved_amount_cents exceeds amount_claimed_cents.")
    c["approved_amount_cents"] = approved_amount_cents
    c["status"] = "APPROVED"
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/deny")
def deny_claim(claimId):
    require_roles("TPAAdjuster", "CarrierUnderwriter")
    c = get_or_404(STORE.claims, claimId, "Claim")
    program = STORE.programs[c["program_id"]]
    body = get_body()
    denial_reason = req_str(body, "denial_reason")
    if g.user_role == "TPAAdjuster":
        require_tpa_owner(c)
        if c["status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "A TPA adjuster may deny only from UNDER_REVIEW.")
        _require_appointment_active(c)
    else:
        require_carrier_owner(program)
        if c["status"] not in ("UNDER_REVIEW", "REFERRED"):
            raise_err(ERR_INVALID_STATE, "The carrier may deny only from UNDER_REVIEW or REFERRED.")
    c["status"] = "DENIED"
    c["denial_reason"] = denial_reason
    c["denied_at"] = now_dt()
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/pay")
def pay_claim(claimId):
    require_roles("TPAAdjuster")
    c = get_or_404(STORE.claims, claimId, "Claim")
    require_tpa_owner(c)
    if c["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED claim can be paid.")
    program = STORE.programs[c["program_id"]]
    # Fiduciary guard: a claim payment may never take the trust balance negative.
    if program["trust_balance_cents"] < c["approved_amount_cents"]:
        raise_err(ERR_TRUST_INSUFFICIENT_FUNDS, "Claim payment exceeds the program trust balance.")
    trust.post_entry(program, "CLAIM_PAYMENT", -c["approved_amount_cents"], claim=c)
    c["paid_cents"] = c["approved_amount_cents"]
    c["paid_at"] = now_dt()
    c["case_reserve_cents"] = 0
    c["status"] = "PAID"
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/reopen")
def reopen_claim(claimId):
    require_roles("MGAUnderwriter")
    c = get_or_404(STORE.claims, claimId, "Claim")
    if c["status"] != "DENIED":
        raise_err(ERR_INVALID_STATE, "Only a DENIED claim can be reopened.")
    if now_dt() - c["denied_at"] > timedelta(days=REOPEN_WINDOW_DAYS):
        raise_err(ERR_REOPEN_WINDOW_CLOSED, "More than 90 days have passed since the denial.")
    if c["reopened_count"] >= MAX_REOPENS:
        raise_err(ERR_REOPEN_LIMIT_EXCEEDED, "The claim has already been reopened %d times." % MAX_REOPENS)
    c["status"] = "REOPENED"
    c["reopened_count"] += 1
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/resume-review")
def resume_review(claimId):
    require_roles("TPAAdjuster")
    c = get_or_404(STORE.claims, claimId, "Claim")
    require_tpa_owner(c)
    if c["status"] != "REOPENED":
        raise_err(ERR_INVALID_STATE, "Only a REOPENED claim can resume review.")
    _require_appointment_active(c)
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(serialize.claim(c))


@bp.post("/mga/claims/<claimId>/close")
def close_claim(claimId):
    require_roles("CarrierUnderwriter")
    c = get_or_404(STORE.claims, claimId, "Claim")
    program = STORE.programs[c["program_id"]]
    require_carrier_owner(program)
    if c["status"] not in ("PAID", "DENIED"):
        raise_err(ERR_INVALID_STATE, "Only a PAID or DENIED claim can be closed.")
    c["status"] = "CLOSED"
    touch(c)
    return success_object(serialize.claim(c))
