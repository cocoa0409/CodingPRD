"""Session routes — including the all-important /complete cascade."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_forbidden,
    err_no_active_supervisor,
    err_not_found,
    err_session_not_open,
    err_therapist_not_active,
)
from ..helpers import (
    new_uuid,
)
from ..responses import ok
from ..services.calculations import (
    licensure_exam_eligible,
    patient_responsibility_in_network,
    sliding_fee_charge_cents,
    supervision_credit_for_type,
    compute_new_accrued,
)
from ..services.cascades import bump
from ..services.serialize import serialize_session
from ..store import store

bp = Blueprint("sessions", __name__, url_prefix="/practice/sessions")


def _has_active_assignment(s, tid: str) -> bool:
    return any(a["therapist_id"] == tid and a["status"] == "ACTIVE"
               for a in s.supervision_assignments.values())


@bp.get("/<sid>")
@require_roles("PracticeAdmin", "Therapist", "BillingClerk")
def get_session(sid: str, **_):
    s = store()
    row = s.sessions.get(sid)
    if row is None:
        raise err_not_found("Session not found")
    return ok(serialize_session(row))


@bp.post("/<sid>/complete")
@require_roles("Therapist")
def complete_session(sid: str, _caller_id: str, _caller_role: str, **_):
    s = store()
    with s.lock:
        sess = s.sessions.get(sid)
        if sess is None:
            raise err_not_found("Session not found")
        appt = s.appointments[sess["appointment_id"]]
        # Ownership: Therapist must own this session.
        if _caller_id != appt["therapist_id"]:
            raise err_forbidden("Therapist may only complete their own sessions")
        # Session-state precondition.
        if sess["status"] != "IN_PROGRESS":
            raise err_session_not_open()
        # Owning appointment must be CHECKED_IN.
        if appt["status"] != "CHECKED_IN":
            raise err_session_not_open()

        therapist = s.therapists[appt["therapist_id"]]
        # Therapist credential must be PROVISIONAL or ACTIVE.
        if therapist["credential_status"] not in {"PROVISIONAL", "ACTIVE"}:
            raise err_therapist_not_active()
        # PRE_LICENSED requires active supervision assignment.
        if therapist["supervision_track"] == "PRE_LICENSED":
            if not _has_active_assignment(s, therapist["id"]):
                raise err_no_active_supervisor()

        # ------- Mutate session and appointment ------------------------------
        delta = supervision_credit_for_type(sess["type"])
        sess["supervision_credit_hours"] = delta
        sess["status"] = "COMPLETED"
        bump(sess)
        appt["status"] = "COMPLETED"
        bump(appt)

        # ------- Auto-post BillingClaim --------------------------------------
        patient = s.patients[appt["patient_id"]]
        plan_id = patient.get("insurance_plan_id")
        plan = s.insurance_plans.get(plan_id) if plan_id else None
        in_network = plan is not None and plan["network_status"] == "IN_NETWORK"
        ts = now()

        if in_network:
            allowed = (
                plan["allowed_amount_90791_cents"] if appt["cpt_code"] == "90791"
                else plan["allowed_amount_90834_cents"]
            )
            charged, patient_resp, insurer_paid = patient_responsibility_in_network(
                allowed_cents=allowed,
                contract_mode=plan["contract_mode"],
                copay_cents=plan["copay_cents"],
                deductible_remaining_cents=patient["deductible_remaining_cents"],
            )
            billing_mode = "INSURANCE_IN_NETWORK"
            # Decrement deductible by exactly the amount the patient paid against it (the deductible-first phase).
            # When contract_mode = DEDUCTIBLE_FIRST and deductible_remaining > 0, patient_resp == min(allowed, remaining).
            # In COPAY_ONLY or DEDUCTIBLE_FIRST after-met phases, no deductible consumption occurs.
            consumed = 0
            if plan["contract_mode"] == "DEDUCTIBLE_FIRST" and patient["deductible_remaining_cents"] > 0:
                consumed = min(allowed, patient["deductible_remaining_cents"])
                patient["deductible_remaining_cents"] -= consumed
                bump(patient)
            claim_plan_id = plan["id"]
        else:
            # SELF_PAY mode (insurance null, or plan is OUT_OF_NETWORK)
            rack = (
                therapist["pricing_rack_90791_cents"] if appt["cpt_code"] == "90791"
                else therapist["pricing_rack_90834_cents"]
            )
            charged = sliding_fee_charge_cents(rack, patient["sliding_fee_tier_pct"])
            patient_resp = charged
            insurer_paid = 0
            billing_mode = "SELF_PAY"
            consumed = 0
            claim_plan_id = None

        cid = new_uuid()
        claim: dict[str, Any] = {
            "id": cid,
            "appointment_id": appt["id"],
            "patient_id": appt["patient_id"],
            "insurance_plan_id": claim_plan_id,
            "cpt_code": appt["cpt_code"],
            "billing_mode": billing_mode,
            "charged_amount_cents": charged,
            "patient_responsibility_cents": patient_resp,
            "insurer_paid_cents": insurer_paid,
            "status": "POSTED",
            "posted_at": ts,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            # Internal bookkeeping: capture amount consumed against deductible for clean reversal.
            "_deductible_consumed_cents": consumed,
        }
        s.billing_claims[cid] = claim

        # ------- Supervision-hour ledger update ------------------------------
        new_total = compute_new_accrued(therapist["supervision_hours_accrued"], delta)
        therapist["supervision_hours_accrued"] = new_total
        therapist["licensure_exam_eligible"] = licensure_exam_eligible(
            new_total, therapist["credential_status"]
        )
        bump(therapist)

        return ok(serialize_session(sess))


@bp.post("/<sid>/void")
@require_roles("PracticeAdmin")
def void_session(sid: str, **_):
    s = store()
    with s.lock:
        sess = s.sessions.get(sid)
        if sess is None:
            raise err_not_found("Session not found")
        if sess["status"] != "IN_PROGRESS":
            raise err_session_not_open()
        appt = s.appointments[sess["appointment_id"]]
        sess["status"] = "VOIDED"
        bump(sess)
        appt["status"] = "CANCELLED"
        appt["hold_reason"] = None
        bump(appt)
        return ok(serialize_session(sess))
