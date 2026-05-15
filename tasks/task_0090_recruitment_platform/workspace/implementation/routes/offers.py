"""Offer routes."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from flask import Blueprint, jsonify

from auth import get_caller, require_hr_bound_to_company, require_roles
from clock import clock, format_iso, parse_iso
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OFFER_EXPIRED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SEGREGATION_VIOLATION,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, require_field
from response import success_object
from services.commission import clawback_record, maybe_create_for_trigger
from store import append_audit, bump, init_common_fields, lock, store


bp = Blueprint("offers", __name__)


_RESCISSION_REASONS = {"BUSINESS_NEED", "BACKGROUND_FAIL", "CANDIDATE_MISREP", "OTHER"}


def _serialize(o: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(o)
    # Projected seconds_remaining while ISSUED
    if out.get("offer_status") == "ISSUED":
        try:
            deadline = parse_iso(out["acceptance_deadline_at"])
            remaining = (deadline - clock.now()).total_seconds()
            out["seconds_remaining"] = max(0, int(remaining))
        except Exception:
            pass
    elif out.get("offer_status") in {"ACCEPTED", "DECLINED", "EXPIRED"}:
        # Freeze at terminal_event_time - issued_at, where terminal_event_time
        # is the recorded transition timestamp (accepted_at for ACCEPTED,
        # declined_at for DECLINED, expired_at for EXPIRED; otherwise the
        # most recent updated_at).
        try:
            issued = parse_iso(out["issued_at"]) if out.get("issued_at") else None
            if issued is not None:
                term_ts = None
                if out.get("offer_status") == "ACCEPTED":
                    term_ts = out.get("accepted_at") or out.get("updated_at")
                elif out.get("offer_status") == "DECLINED":
                    term_ts = out.get("declined_at") or out.get("updated_at")
                elif out.get("offer_status") == "EXPIRED":
                    term_ts = out.get("expired_at") or out.get("updated_at")
                if term_ts:
                    term = parse_iso(term_ts)
                    out["seconds_remaining"] = max(0, int((term - issued).total_seconds()))
        except Exception:
            pass
    return out


@bp.post("/recruitment/offers")
def create_offer():
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    body = get_json_body()
    application_id = require_field(body, "application_id")
    base_salary_cents = require_field(body, "base_salary_cents")
    sign_on_bonus_cents = body.get("sign_on_bonus_cents", 0)

    application = store.applications.get(application_id)
    if application is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "application_id not found.")
    require_hr_bound_to_company(caller, application["company_id"])

    if not isinstance(base_salary_cents, int) or isinstance(base_salary_cents, bool):
        raise_err(ERR_VALIDATION, "base_salary_cents must be an integer.")
    if not isinstance(sign_on_bonus_cents, int) or isinstance(sign_on_bonus_cents, bool):
        raise_err(ERR_VALIDATION, "sign_on_bonus_cents must be an integer.")
    if base_salary_cents <= 0 or sign_on_bonus_cents < 0:
        raise_err(ERR_INVALID_AMOUNT, "Offer amounts invalid.")

    # Uniqueness on application_id
    for o in store.offers.values():
        if o.get("application_id") == application_id:
            raise_err(ERR_VALIDATION, "Offer already exists for application.")

    row = init_common_fields(
        {
            "application_id": application_id,
            "company_id": application["company_id"],
            "base_salary_cents": base_salary_cents,
            "sign_on_bonus_cents": sign_on_bonus_cents,
            "offer_status": "DRAFT",
            "hm_approver_user_id": None,
            "hr_approver_user_id": None,
            "finance_approver_user_id": None,
            "issued_at": None,
            "acceptance_deadline_at": None,
            "accepted_at": None,
            "declined_at": None,
            "expired_at": None,
            "competing_offer_note": None,
            "rescission_reason": None,
        }
    )
    store.offers[row["id"]] = row
    body_out, status = success_object(_serialize(row), 201)
    return jsonify(body_out), status


@bp.post("/recruitment/offers/<oid>/submit-approval")
def submit_approval(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    require_hr_bound_to_company(caller, offer["company_id"])
    body = get_json_body()
    check_version(body, offer)
    if offer["offer_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Offer not DRAFT.")

    application = store.applications.get(offer["application_id"])
    if application is None:
        raise_err(ERR_INVALID_STATE, "Application missing.")
    if application["application_status"] != "INTERVIEW":
        raise_err(ERR_INVALID_STATE, "Application not in INTERVIEW.")
    # at least one InterviewRound on the Application has round_status PASSED
    rounds = [r for r in store.interview_rounds.values() if r.get("application_id") == application["id"]]
    if not any(r.get("round_status") == "PASSED" for r in rounds):
        raise_err(ERR_INVALID_STATE, "No PASSED interview round.")
    # Re-check amounts (priority 17 applies to submit-approval)
    if int(offer["base_salary_cents"]) <= 0 or int(offer["sign_on_bonus_cents"]) < 0:
        raise_err(ERR_INVALID_AMOUNT, "Offer amounts invalid.")

    offer["offer_status"] = "PENDING_HM"
    bump(offer)
    append_audit(
        subject_entity="Offer",
        subject_id=offer["id"],
        event_kind="STATE_TRANSITION",
        from_state="DRAFT",
        to_state="PENDING_HM",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(offer))
    return jsonify(body_out), status


@bp.post("/recruitment/offers/<oid>/approve")
def approve_offer(oid: str):
    caller = get_caller()
    require_roles(caller, ["HiringManager", "HrApprover", "FinanceApprover"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    require_hr_bound_to_company(caller, offer["company_id"])
    body = get_json_body()
    check_version(body, offer)

    status_ = offer["offer_status"]
    role = caller.role
    actor_id = caller.user_id

    if role == "HiringManager":
        if status_ != "PENDING_HM":
            raise_err(ERR_INVALID_STATE, "Offer not awaiting HM approval.")
        offer["hm_approver_user_id"] = actor_id
        offer["offer_status"] = "PENDING_HR"
        from_state = "PENDING_HM"
        to_state = "PENDING_HR"
    elif role == "HrApprover":
        if status_ != "PENDING_HR":
            raise_err(ERR_INVALID_STATE, "Offer not awaiting HR approval.")
        if actor_id == offer.get("hm_approver_user_id"):
            raise_err(ERR_SEGREGATION_VIOLATION, "HR approver must differ from HM.")
        offer["hr_approver_user_id"] = actor_id
        offer["offer_status"] = "PENDING_FINANCE"
        from_state = "PENDING_HR"
        to_state = "PENDING_FINANCE"
    else:  # FinanceApprover
        if status_ != "PENDING_FINANCE":
            raise_err(ERR_INVALID_STATE, "Offer not awaiting Finance approval.")
        if actor_id == offer.get("hm_approver_user_id") or actor_id == offer.get("hr_approver_user_id"):
            raise_err(ERR_SEGREGATION_VIOLATION, "Finance approver must differ from HM and HR.")
        offer["finance_approver_user_id"] = actor_id
        offer["offer_status"] = "ISSUED"
        now = clock.now()
        offer["issued_at"] = format_iso(now)
        offer["acceptance_deadline_at"] = format_iso(now + timedelta(hours=168))
        from_state = "PENDING_FINANCE"
        to_state = "ISSUED"

    bump(offer)
    append_audit(
        subject_entity="Offer",
        subject_id=offer["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state=to_state,
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, http_status = success_object(_serialize(offer))
    return jsonify(body_out), http_status


@bp.post("/recruitment/offers/<oid>/reject-approval")
def reject_approval(oid: str):
    caller = get_caller()
    require_roles(caller, ["HiringManager", "HrApprover", "FinanceApprover"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    require_hr_bound_to_company(caller, offer["company_id"])
    body = get_json_body()
    check_version(body, offer)

    status_ = offer["offer_status"]
    role = caller.role

    if role == "HiringManager":
        if status_ != "PENDING_HM":
            raise_err(ERR_INVALID_STATE, "Offer not awaiting HM approval.")
        from_state = "PENDING_HM"
        offer["offer_status"] = "DRAFT"
    elif role == "HrApprover":
        if status_ != "PENDING_HR":
            raise_err(ERR_INVALID_STATE, "Offer not awaiting HR approval.")
        from_state = "PENDING_HR"
        offer["offer_status"] = "DRAFT"
        offer["hm_approver_user_id"] = None
    else:  # FinanceApprover
        if status_ != "PENDING_FINANCE":
            raise_err(ERR_INVALID_STATE, "Offer not awaiting Finance approval.")
        from_state = "PENDING_FINANCE"
        offer["offer_status"] = "DRAFT"
        offer["hm_approver_user_id"] = None
        offer["hr_approver_user_id"] = None

    bump(offer)
    append_audit(
        subject_entity="Offer",
        subject_id=offer["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state="DRAFT",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, http_status = success_object(_serialize(offer))
    return jsonify(body_out), http_status


@bp.post("/recruitment/offers/<oid>/accept")
def accept_offer(oid: str):
    caller = get_caller()
    require_roles(caller, ["Candidate"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    application = store.applications.get(offer["application_id"])
    if application is None:
        raise_err(ERR_NOT_FOUND, "Parent application missing.")
    if application.get("candidate_id") != caller.user_id:
        raise_err(ERR_FORBIDDEN, "Cannot accept another candidate's offer.")
    body = get_json_body()
    check_version(body, offer)

    # PRD §2.9: first-writer-wins serialization on offer_status for the
    # accept-vs-rescind race. The state check and the write must be atomic.
    with lock():
        if offer["offer_status"] != "ISSUED":
            raise_err(ERR_INVALID_STATE, "Offer not ISSUED.")
        deadline = parse_iso(offer["acceptance_deadline_at"])
        if clock.now() >= deadline:
            raise_err(ERR_OFFER_EXPIRED, "Offer acceptance window has expired.")

        competing_note = body.get("competing_offer_note")
        if competing_note is not None and not isinstance(competing_note, str):
            raise_err(ERR_VALIDATION, "competing_offer_note must be a string.")
        if competing_note is not None:
            offer["competing_offer_note"] = competing_note

        now = clock.now()
        offer["offer_status"] = "ACCEPTED"
        offer["accepted_at"] = format_iso(now)
        bump(offer)
        append_audit(
            subject_entity="Offer",
            subject_id=offer["id"],
            event_kind="STATE_TRANSITION",
            from_state="ISSUED",
            to_state="ACCEPTED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
        # Maybe create commission record
        maybe_create_for_trigger(
            application=application,
            offer=offer,
            expected_trigger="OFFER_ACCEPTED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
    body_out, http_status = success_object(_serialize(offer))
    return jsonify(body_out), http_status


@bp.post("/recruitment/offers/<oid>/decline")
def decline_offer(oid: str):
    caller = get_caller()
    require_roles(caller, ["Candidate"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    application = store.applications.get(offer["application_id"])
    if application is None:
        raise_err(ERR_NOT_FOUND, "Parent application missing.")
    if application.get("candidate_id") != caller.user_id:
        raise_err(ERR_FORBIDDEN, "Cannot decline another candidate's offer.")
    body = get_json_body()
    check_version(body, offer)
    if offer["offer_status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "Offer not ISSUED.")
    offer["offer_status"] = "DECLINED"
    offer["declined_at"] = format_iso(clock.now())
    bump(offer)
    append_audit(
        subject_entity="Offer",
        subject_id=offer["id"],
        event_kind="STATE_TRANSITION",
        from_state="ISSUED",
        to_state="DECLINED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, http_status = success_object(_serialize(offer))
    return jsonify(body_out), http_status


def rescind_offer_internal(offer: Dict[str, Any], rescission_reason: str,
                           actor_role: str, actor_user_id: str) -> None:
    """Apply rescission to an offer in ISSUED or ACCEPTED. Caller must have
    already validated state, reason, and any onboarding-exists guards."""
    from_state = offer["offer_status"]
    offer["offer_status"] = "RESCINDED"
    offer["rescission_reason"] = rescission_reason
    bump(offer)
    append_audit(
        subject_entity="Offer",
        subject_id=offer["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state="RESCINDED",
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    if from_state == "ACCEPTED":
        # Commission clawback for ACCRUED records with trigger_kind=OFFER_ACCEPTED
        for rec in list(store.commission_records.values()):
            if rec.get("application_id") != offer["application_id"]:
                continue
            if rec.get("settlement_status") != "ACCRUED":
                continue
            if rec.get("trigger_kind") != "OFFER_ACCEPTED":
                continue
            clawback_record(rec, actor_role, actor_user_id)


@bp.post("/recruitment/offers/<oid>/rescind")
def rescind_offer(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    require_hr_bound_to_company(caller, offer["company_id"])
    body = get_json_body()
    check_version(body, offer)
    reason = require_field(body, "rescission_reason")
    if reason not in _RESCISSION_REASONS:
        raise_err(ERR_VALIDATION, "rescission_reason invalid.")
    # PRD §2.9: first-writer-wins serialization on offer_status for the
    # accept-vs-rescind race.
    with lock():
        if offer["offer_status"] not in {"ISSUED", "ACCEPTED"}:
            raise_err(ERR_INVALID_STATE, "Offer not rescindable.")
        if offer["offer_status"] == "ACCEPTED":
            # No onboarding row may exist for this offer yet.
            for ob in store.onboardings.values():
                if ob.get("offer_id") == offer["id"]:
                    raise_err(ERR_INVALID_STATE, "Onboarding already exists for offer.")
        rescind_offer_internal(offer, reason, caller.role, caller.user_id)
    body_out, http_status = success_object(_serialize(offer))
    return jsonify(body_out), http_status


@bp.get("/recruitment/offers/<oid>")
def get_offer(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "Candidate"])
    offer = store.offers.get(oid)
    if offer is None:
        raise_err(ERR_NOT_FOUND, "Offer not found.")
    if caller.role == "Candidate":
        application = store.applications.get(offer["application_id"])
        if application is None or application.get("candidate_id") != caller.user_id:
            raise_err(ERR_FORBIDDEN, "Cannot view another candidate's offer.")
    else:
        require_hr_bound_to_company(caller, offer["company_id"])
    body_out, status = success_object(_serialize(offer))
    return jsonify(body_out), status
